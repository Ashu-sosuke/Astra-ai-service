import logging
import os
import tempfile
import subprocess
import time
import asyncio
import httpx
import wave
import torch
from faster_whisper import WhisperModel
from config import config

logger = logging.getLogger(__name__)

def _convert_to_wav(audio_path: str) -> str:
    """
    Convert any audio file (m4a, ogg, mp3, etc.) to WAV using ffmpeg.
    Returns the path to the converted WAV file.
    """
    wav_path = tempfile.mktemp(suffix=".wav")
    
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"
    
    cmd = [
        ffmpeg_exe, "-y", "-i", audio_path,
        "-ar", "16000",
        "-ac", "1",
        "-f", "wav",
        wav_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"FFmpeg conversion failed: {result.stderr[:500]}")
            return audio_path
        logger.info(f"Converted audio to WAV for transcription")
        return wav_path
    except FileNotFoundError:
        logger.warning("FFmpeg not found, using original file")
        return audio_path
    except Exception as e:
        logger.warning(f"Audio conversion error: {e}")
        return audio_path

def _get_wav_duration(file_path: str) -> float:
    """
    Retrieves the duration in seconds of a WAV file.
    """
    try:
        with wave.open(file_path, 'r') as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return frames / float(rate)
    except Exception as e:
        logger.debug(f"Could not parse WAV duration: {e}")
        return 0.0

class TranscriptionService:
    def __init__(self):
        # Read GROQ_WHISPER flag from env / config
        self.groq_whisper = config.GROQ_WHISPER
        self.model = None
        
        # Configure GPU paths for Windows if needed
        if os.name == 'nt':
            try:
                import nvidia.cublas.lib
                import nvidia.cudnn.lib
                logger.info("Injecting NVIDIA cuBLAS and cuDNN DLL paths for Windows GPU support...")
                cublas_path = os.path.dirname(nvidia.cublas.lib.__file__)
                cudnn_path = os.path.dirname(nvidia.cudnn.lib.__file__)
                os.add_dll_directory(cublas_path)
                os.add_dll_directory(cudnn_path)
                os.environ["PATH"] = cublas_path + os.pathsep + cudnn_path + os.pathsep + os.environ.get("PATH", "")
            except ImportError as e:
                logger.debug(f"NVIDIA pip modules not found to inject DLLs: {e}")

        # Load model immediately if Groq Whisper is NOT active
        if not self.groq_whisper:
            logger.info("Groq Whisper is disabled. Loading local Whisper model at startup...")
            self._init_local_model()
        else:
            logger.info("Groq Whisper is enabled. Local Whisper will serve as fallback and load lazily.")

    def _init_local_model(self):
        """Loads the local Whisper model once as a singleton."""
        if self.model is not None:
            return
            
        # Fallback uses 'base' model as requested, otherwise uses config size
        model_size = "base" if self.groq_whisper else config.WHISPER_MODEL_SIZE
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        
        logger.info(f"Loading local Whisper model '{model_size}' on '{device}'...")
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            logger.info(f"Local Whisper model '{model_size}' loaded successfully.")
        except Exception as e:
            logger.critical(f"Failed to load local Whisper model: {e}")
            raise e

    async def transcribe(self, audio_path: str) -> dict:
        """
        Transcribes the audio file. Supports both Groq Whisper API and local faster-whisper.
        Logs latency and handles fallback errors.
        """
        start_time = time.time()
        
        # PATH A: Groq Whisper API
        if self.groq_whisper:
            try:
                logger.info("Route A: Transcribing via Groq Whisper API...")
                result = await self._transcribe_groq(audio_path)
                latency_ms = int((time.time() - start_time) * 1000)
                logger.info(f"Groq Transcription SUCCESS | Latency: {latency_ms}ms")
                return result
            except Exception as e:
                logger.error(f"Groq Whisper transcription failed: {e}. Falling back to Local Whisper...")
        
        # PATH B: Local Whisper Fallback
        try:
            logger.info("Route B: Transcribing via Local Whisper...")
            self._init_local_model()
            result = await self._transcribe_local(audio_path)
            latency_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Local Transcription SUCCESS | Latency: {latency_ms}ms")
            return result
        except Exception as e:
            logger.error(f"Local Whisper transcription failed: {e}")
            raise ValueError(f"Transcription failed on both paths: {e}")

    async def _transcribe_groq(self, audio_path: str) -> dict:
        """Calls Groq Whisper API asynchronously."""
        api_key = config.GROQ_API_KEY
        if not api_key:
            raise ValueError("GROQ_API_KEY is not configured in environment")
            
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        # Convert audio to wav first for consistent API results
        converted_path = audio_path
        if not audio_path.lower().endswith('.wav'):
            converted_path = _convert_to_wav(audio_path)
            
        duration = _get_wav_duration(converted_path)
        
        try:
            # We open and read the file asynchronously or send as multipart
            with open(converted_path, 'rb') as f:
                files = {
                    "file": (os.path.basename(converted_path), f, "audio/wav")
                }
                data = {
                    "model": "whisper-large-v3-turbo",
                    "response_format": "json"
                }
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, headers=headers, files=files, data=data, timeout=30.0)
                    
            if response.status_code != 200:
                response.raise_for_status()
                
            res_json = response.json()
            text = res_json.get("text", "").strip()
            
            return {
                "language": "en",
                "duration": duration,
                "text": text if text else "[No speech detected]",
                "segments": []
            }
        finally:
            if converted_path != audio_path and os.path.exists(converted_path):
                try:
                    os.remove(converted_path)
                except:
                    pass

    async def _transcribe_local(self, audio_path: str) -> dict:
        """Runs local faster-whisper transcription inside a thread pool."""
        converted_path = None
        try:
            if not audio_path.lower().endswith('.wav'):
                converted_path = _convert_to_wav(audio_path)
            else:
                converted_path = audio_path
                
            duration = _get_wav_duration(converted_path)
            loop = asyncio.get_event_loop()
            
            # Helper to run synchronous model.transcribe in executor
            def run_whisper_sync(path, use_vad):
                segments_generator, info = self.model.transcribe(
                    path, 
                    beam_size=5, 
                    vad_filter=use_vad,
                    language=None
                )
                # We must consume the generator inside the worker thread to do the actual CPU computations
                segments_list = list(segments_generator)
                return segments_list, info

            # First try without VAD filter
            segments, info = await loop.run_in_executor(None, run_whisper_sync, converted_path, False)
            
            text_segments = []
            full_text = []
            for segment in segments:
                text_segments.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text
                })
                full_text.append(segment.text)
                
            combined_text = " ".join(full_text).strip()
            
            # Fallback with VAD filter if empty
            if not combined_text:
                logger.warning("Empty transcript without VAD. Retrying with VAD filter...")
                segments, info = await loop.run_in_executor(None, run_whisper_sync, converted_path, True)
                text_segments = []
                full_text = []
                for segment in segments:
                    text_segments.append({
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text
                    })
                    full_text.append(segment.text)
                combined_text = " ".join(full_text).strip()

            return {
                "language": info.language,
                "duration": duration if duration > 0 else info.duration,
                "text": combined_text if combined_text else "[No speech detected]",
                "segments": text_segments
            }
            
        except Exception as e:
            error_msg = str(e)
            if "cublas" in error_msg.lower() or "cudnn" in error_msg.lower() or "cuda" in error_msg.lower():
                logger.error(f"GPU Transcription failed due to missing CUDA libraries: {e}")
                logger.info("Falling back to CPU for Local Whisper...")
                
                # Recreate the model on CPU and try again
                loop = asyncio.get_event_loop()
                def init_cpu_model():
                    model_size = "base" if self.groq_whisper else config.WHISPER_MODEL_SIZE
                    self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
                    
                await loop.run_in_executor(None, init_cpu_model)
                return await self._transcribe_local(audio_path)
            else:
                logger.error(f"Local transcription error: {e}")
                raise
        finally:
            if converted_path and converted_path != audio_path and os.path.exists(converted_path):
                try:
                    os.remove(converted_path)
                except:
                    pass
