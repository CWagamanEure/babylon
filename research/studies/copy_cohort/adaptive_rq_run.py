"""Explicit frozen entry point for the adaptive-R/Q powered diagnostic."""

from .adaptive_rq_filter import PROFILE_ID, run

if __name__ == "__main__":
    run(profile_id=PROFILE_ID)
