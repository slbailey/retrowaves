import numpy as np


class Mixer:
    """
    Simple pass-through mixer that applies gain only.
    
    ARCHITECTURAL INVARIANT: No timing logic. Processes frames immediately.
    Station pushes frames as fast as decoder produces them - Tower owns all timing.
    """

    def mix(self, frame: np.ndarray, gain: float = 1.0) -> np.ndarray:
        if gain == 1.0:
            return frame
        # Apply gain in float then clip back to int16
        out = frame.astype(np.float32) * float(gain)
        np.clip(out, -32768.0, 32767.0, out=out)
        return out.astype(np.int16)


