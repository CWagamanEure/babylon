"""Hyperliquid network endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from babylon.config import Network

MAINNET_API_URL = "https://api.hyperliquid.xyz"
TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"


@dataclass(frozen=True, slots=True)
class Endpoints:
    rest: str
    ws: str


def endpoints_for(network: Network) -> Endpoints:
    base = MAINNET_API_URL if network is Network.MAINNET else TESTNET_API_URL
    ws = base.replace("https://", "wss://") + "/ws"
    return Endpoints(rest=base, ws=ws)
