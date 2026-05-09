import librosa
import numpy as np
import logging
import os
import tempfile
import subprocess

logger = logging.getLogger(__name__)

def _convert_to_wav(audio_path: str) -> str:
    """
    Convert any audio file (m4a, ogg, mp3, etc.) to WAV using ffmpeg.
    Returns the path to the converted WAV file.
    """
    wav_path = tempfile.mktemp(suffix=".wav")
    
    # Try to find ffmpeg from imageio_ffmpeg (bundled) first, then system PATH
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"
    
    cmd = [
        ffmpeg_exe, "-y", "-i", audio_path,
        "-ar", "16000",    # 16kHz sample rate
        "-ac", "1",        # mono
        "-f", "wav",
        wav_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"FFmpeg conversion failed: {result.stderr[:500]}")
            return audio_path  # fallback to original
        logger.info(f"Converted {audio_path} -> WAV successfully")
        return wav_path
    except FileNotFoundError:
        logger.warning("FFmpeg not found. Attempting to load audio directly.")
        return audio_path
    except Exception as e:
        logger.warning(f"FFmpeg conversion error: {e}. Using original file.")
        return audio_path


class AudioStressDetector:
    def __init__(self):
        # Constants for heuristics (calibrated for standard speech)
        self.PITCH_THRESHOLD = 250.0  # Hz, simplistic high pitch threshold
        self.ENERGY_THRESHOLD = 0.03  # RMS energy threshold
        
    def analyze(self, audio_path: str) -> dict:
        """
        Analyzes audio for stress indicators using acoustic features.
        Returns a dictionary with stress score and details.
        """
        converted_path = None
        try:
            # Convert M4A/other formats to WAV first
            if not audio_path.lower().endswith('.wav'):
                converted_path = _convert_to_wav(audio_path)
            else:
                converted_path = audio_path

            # Load audio (downsample to 16kHz for speed)
            y, sr = librosa.load(converted_path, sr=16000)
            
            if len(y) == 0:
                logger.warning("Audio file is empty after loading.")
                return {"stress_score": 0.0, "details": {"metrics": ["Empty audio"]}}
            
            # 1. RMS Energy (Loudness/Intensity)
            rms = librosa.feature.rms(y=y)
            avg_energy = np.mean(rms)
            
            # 2. Pitch (Fundamental Frequency - F0) using pYIN
            f0, voiced_flag, voiced_probs = librosa.pyin(
                y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7')
            )
            
            # Filter distinct pitches
            valid_pitches = f0[~np.isnan(f0)]
            avg_pitch = np.mean(valid_pitches) if len(valid_pitches) > 0 else 0
            
            # 3. Speech Rate / Zero Crossing Rate (Agitation)
            zcr = librosa.feature.zero_crossing_rate(y)
            avg_zcr = np.mean(zcr)
            
            # heuristic scoring (0.0 to 1.0)
            score = 0.0
            explanations = []

        # Energy Contribution (0.4 max)
            if avg_energy > self.ENERGY_THRESHOLD:
                score += 0.4
                explanations.append("High voice intensity detected")
            elif avg_energy > self.ENERGY_THRESHOLD * 0.6:
                score += 0.25
                explanations.append("Moderate voice intensity")
            elif avg_energy > self.ENERGY_THRESHOLD * 0.3:
                score += 0.1
            
            # Pitch Contribution (0.4 max)
            if avg_pitch > self.PITCH_THRESHOLD:
                score += 0.4
                explanations.append("High pitch/screaming detected")
            elif avg_pitch > self.PITCH_THRESHOLD * 0.8:
                score += 0.25
                explanations.append("Elevated pitch detected")
            elif avg_pitch > self.PITCH_THRESHOLD * 0.6:
                score += 0.1
                
            # ZCR/Agitation (0.2 max)
            if avg_zcr > 0.08:
                score += 0.2
                explanations.append("Rapid/agitated speech pattern")
            elif avg_zcr > 0.05:
                score += 0.1
                explanations.append("Slightly agitated pattern")

            logger.info(f"Stress analysis complete: score={score}, energy={avg_energy:.4f}, pitch={avg_pitch:.1f}Hz, zcr={avg_zcr:.4f}")
                
            return {
                "stress_score": round(min(score, 1.0), 2),
                "details": {
                    "avg_pitch_hz": float(round(avg_pitch, 2)),
                    "avg_energy": float(round(avg_energy, 4)),
                    "avg_zcr": float(round(avg_zcr, 4)),
                    "metrics": explanations
                }
            }
            
        except Exception as e:
            import traceback
            logger.error(f"Emotion analysis failed: {str(e)}\n{traceback.format_exc()}")
            return {"stress_score": 0.0, "error": str(e), "details": {"metrics": ["Analysis failed"]}}
        finally:
            # Clean up converted file
            if converted_path and converted_path != audio_path and os.path.exists(converted_path):
                try:
                    os.remove(converted_path)
                except:
                    pass
