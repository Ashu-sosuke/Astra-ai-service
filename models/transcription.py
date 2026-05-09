import logging
import os
import tempfile
import subprocess
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


class TranscriptionService:
    def __init__(self):
        import torch
        import os
        
        # Windows-specific fix for NVIDIA DLLs when using PIP-installed CUDA Toolkit
        if os.name == 'nt':
            try:
                import nvidia.cublas.lib
                import nvidia.cudnn.lib
                logger.info("Injecting NVIDIA cuBLAS and cuDNN DLL paths for Windows GPU support...")
                
                cublas_path = os.path.dirname(nvidia.cublas.lib.__file__)
                cudnn_path = os.path.dirname(nvidia.cudnn.lib.__file__)
                
                # add_dll_directory works for Python ctypes
                os.add_dll_directory(cublas_path)
                os.add_dll_directory(cudnn_path)
                
                # Appending to PATH is required for CTranslate2 C++ engine 
                os.environ["PATH"] = cublas_path + os.pathsep + cudnn_path + os.pathsep + os.environ.get("PATH", "")
                
            except ImportError as e:
                logger.debug(f"NVIDIA pip modules not found to inject DLLs: {e}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        
        logger.info(f"Loading Whisper model: {config.WHISPER_MODEL_SIZE} on {device}...")
        try:
            self.model = WhisperModel(config.WHISPER_MODEL_SIZE, device=device, compute_type=compute_type)
            logger.info(f"Whisper model loaded successfully on {device}.")
        except Exception as e:
            logger.critical(f"Failed to load Whisper model: {e}")
            raise e

    def transcribe(self, audio_path: str) -> dict:
        """
        Transcribes the audio file.
        Returns a dictionary with full text and segments.
        """
        converted_path = None
        try:
            # Convert M4A/other formats to WAV first for reliable processing
            if not audio_path.lower().endswith('.wav'):
                converted_path = _convert_to_wav(audio_path)
            else:
                converted_path = audio_path

            # First try WITHOUT vad_filter (more reliable for short/quiet recordings)
            segments, info = self.model.transcribe(
                converted_path, 
                beam_size=5, 
                vad_filter=False,
                language=None  # auto-detect language
            )
            
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
            
            # If we got nothing, try again WITH vad_filter as a fallback
            if not combined_text:
                logger.warning("Empty transcript without VAD. Retrying with VAD filter...")
                segments, info = self.model.transcribe(converted_path, beam_size=5, vad_filter=True)
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
            
            logger.info(f"Transcription result: lang={info.language}, duration={info.duration:.1f}s, text='{combined_text[:100]}...'")
            
            return {
                "language": info.language,
                "duration": info.duration,
                "text": combined_text if combined_text else "[No speech detected]",
                "segments": text_segments
            }
        except Exception as e:
            error_msg = str(e)
            if "cublas" in error_msg.lower() or "cudnn" in error_msg.lower() or "cuda" in error_msg.lower():
                logger.error(f"GPU Transcription failed due to missing CUDA libraries: {e}")
                logger.info("Falling back to CPU for Whisper transcription...")
                try:
                    # Recreate the model on CPU and try again
                    self.model = WhisperModel(config.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
                    return self.transcribe(audio_path)
                except Exception as fallback_e:
                    logger.error(f"CPU fallback transcription also failed: {fallback_e}")
                    raise ValueError(f"Transcription failed on both GPU and CPU: {str(fallback_e)}")
            else:
                logger.error(f"Transcription failed: {e}")
                raise ValueError(f"Transcription failed: {str(e)}")
        finally:
            if converted_path and converted_path != audio_path and os.path.exists(converted_path):
                try:
                    os.remove(converted_path)
                except:
                    pass
