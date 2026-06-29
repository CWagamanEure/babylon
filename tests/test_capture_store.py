from babylon.follow.capture.markout import FinalRoundtrip
from babylon.follow.capture.store import RoundtripStore


def _rt(wallet, coin, rid, exit_t, ret):
    return FinalRoundtrip(wallet, coin, rid, 1, exit_t - 1000, exit_t, 100.0, 100.0 + ret / 100,
                          ret, True, True, "live")


def test_store_window_returns(tmp_path):
    s = RoundtripStore(tmp_path / "rt.db", batch=2)
    for i in range(5):
        s.add(_rt("w", "ZEC", i, 1000 + i * 100, 10.0 + i))   # exit_t 1000,1100,...,1400
    r = s.returns("w", lo_t=1100, hi_t=1400)                  # [1100,1400): rids 1,2,3
    assert sorted(r.tolist()) == [11.0, 12.0, 13.0]
    assert s.returns("w", 0, 1000).size == 0                  # exit_t 1000 excluded (< hi)
    s.close()


def test_store_persists_and_dedups_rid(tmp_path):
    p = tmp_path / "rt.db"
    s = RoundtripStore(p)
    s.add(_rt("w", "ZEC", 0, 1000, 50.0))
    s.add(_rt("w", "ZEC", 0, 1000, 99.0))                     # same (wallet,coin,rid) → ignored
    s.close()
    s2 = RoundtripStore(p)                                     # reopen → durable
    assert s2.count() == 1 and s2.returns("w", 0, 2000).tolist() == [50.0]
    s2.close()


def test_active_wallets_by_min_n(tmp_path):
    s = RoundtripStore(tmp_path / "rt.db")
    for i in range(3):
        s.add(_rt("active", "ZEC", i, 1000 + i, 10.0))
    s.add(_rt("thin", "SOL", 0, 1000, 10.0))
    assert s.active_wallets(0, 2000, min_n=3) == ["active"]    # thin (1 rt) excluded
    s.close()


def test_prune_retention(tmp_path):
    s = RoundtripStore(tmp_path / "rt.db")
    s.add(_rt("w", "ZEC", 0, 1000, 10.0))                     # old
    s.add(_rt("w", "ZEC", 1, 9000, 20.0))                     # recent
    assert s.prune(before_t=5000) == 1 and s.count() == 1
    assert s.returns("w", 0, 99999).tolist() == [20.0]
    s.close()
