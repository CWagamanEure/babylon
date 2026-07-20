"""Run the single frozen 60-day half-life selector and causal book diagnostic."""

from .dynamic_t_book import run as run_book
from .dynamic_t_quality import HL60_PROFILE
from .dynamic_t_quality import run as run_selector


def run() -> dict:
    run_selector(profile=HL60_PROFILE)
    return run_book(profile=HL60_PROFILE)


if __name__ == "__main__":
    run()
