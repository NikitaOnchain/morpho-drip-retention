#!/usr/bin/env python3
"""Unit tests for the Phase 3 resume-safe archive-RPC cache."""

from __future__ import annotations

import sqlite3
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from morpho_archive_rpc_cache import (
    ArchiveCall,
    ArchiveRpcCache,
    CacheIdentityError,
    CacheIntegrityError,
    CachedArchiveSession,
    IntentionalStop,
)


CHAIN_ID = 42161
CONTRACT = "0x6c247b1f6182318877311737bac0844baa518f5e"
POSITION_SELECTOR = "93c52062"
MARKET_SELECTOR = "5c60e39a"
FEE_SELECTOR = "46904840"
MARKET = "0x" + "11" * 32
WALLET = "0x" + "22" * 20
TEST_ROOT = Path(__file__).resolve().parents[1] / "data" / "tmp"


@contextmanager
def test_database() -> object:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_ROOT / f"morpho_cache_unit_{uuid.uuid4().hex}.sqlite"
    try:
        yield path
    finally:
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            candidate.unlink(missing_ok=True)


def identity(population_hash: str = "aa" * 32) -> dict[str, object]:
    return {
        "selector_cache_version": "test-v1",
        "chain_id": CHAIN_ID,
        "contract_address": CONTRACT,
        "manifest_sha256": "bb" * 32,
        "candidate_population_sha256": population_hash,
    }


def position_call(block: int, wallet: str = WALLET) -> ArchiveCall:
    return ArchiveCall(
        "eth_call",
        "position",
        block,
        MARKET,
        wallet,
        "0x" + POSITION_SELECTOR + MARKET[2:] + wallet[2:].rjust(64, "0"),
        3,
    )


def market_call(block: int) -> ArchiveCall:
    return ArchiveCall(
        "eth_call",
        "market",
        block,
        MARKET,
        "",
        "0x" + MARKET_SELECTOR + MARKET[2:],
        6,
    )


class FakeRpc:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, method: str, params: list[object]) -> str:
        self.calls += 1
        if method != "eth_call" or len(params) != 2:
            raise AssertionError("unexpected RPC request")
        data = str(dict(params[0])["data"])
        words = 3 if data.startswith("0x" + POSITION_SELECTOR) else 6
        return "0x" + "00" * (words * 32)


class ArchiveRpcCacheTests(unittest.TestCase):
    def open_cache(self, path: Path, cache_identity: dict[str, object] | None = None) -> ArchiveRpcCache:
        return ArchiveRpcCache(
            path,
            cache_identity or identity(),
            CONTRACT,
            POSITION_SELECTOR,
            MARKET_SELECTOR,
            FEE_SELECTOR,
        )

    def test_intentional_stop_then_resume_does_not_repeat_rpc(self) -> None:
        with test_database() as path:
            rpc = FakeRpc()
            cache = self.open_cache(path)
            first = CachedArchiveSession(rpc, cache, CONTRACT, max_new_rpc_calls=2)
            plan = [position_call(100), market_call(100), position_call(200), market_call(200)]
            with self.assertRaises(IntentionalStop):
                for call in plan:
                    first.execute(call)
            self.assertEqual(rpc.calls, 2)
            self.assertEqual(cache.audit()["cache_entries"], 2)
            self.assertEqual(cache.audit()["checkpoint_contiguous_through"], 1)
            cache.close()

            cache = self.open_cache(path)
            second = CachedArchiveSession(rpc, cache, CONTRACT)
            for call in plan:
                second.execute(call)
            self.assertEqual(second.cache_hits, 2)
            self.assertEqual(second.new_rpc_calls, 2)
            self.assertEqual(rpc.calls, 4)
            audit = cache.audit()
            self.assertEqual(audit["sqlite_integrity"], "ok")
            self.assertEqual(audit["invalid_entries"], 0)
            self.assertEqual(audit["duplicate_key_groups"], 0)
            self.assertEqual(audit["progress_gaps"], 0)
            self.assertEqual(audit["orphan_progress_rows"], 0)
            cache.close()

    def test_same_call_at_two_ordinals_is_one_rpc_and_two_progress_rows(self) -> None:
        with test_database() as path:
            rpc = FakeRpc()
            cache = self.open_cache(path)
            session = CachedArchiveSession(rpc, cache, CONTRACT)
            call = market_call(123)
            session.execute(call)
            session.execute(call)
            self.assertEqual(rpc.calls, 1)
            self.assertEqual(session.cache_hits, 1)
            audit = cache.audit()
            self.assertEqual(audit["cache_entries"], 1)
            self.assertEqual(audit["progress_rows"], 2)
            self.assertEqual(audit["progress_gaps"], 0)
            cache.close()

    def test_invalid_result_is_not_cached_or_checkpointed(self) -> None:
        with test_database() as path:
            cache = self.open_cache(path)
            session = CachedArchiveSession(lambda _m, _p: "0x1234", cache, CONTRACT)
            with self.assertRaises(CacheIntegrityError):
                session.execute(position_call(100))
            audit = cache.audit()
            self.assertEqual(audit["cache_entries"], 0)
            self.assertEqual(audit["progress_rows"], 0)
            self.assertEqual(audit["checkpoint_contiguous_through"], -1)
            cache.close()

    def test_committed_response_before_checkpoint_resumes_without_rpc(self) -> None:
        with test_database() as path:
            cache = self.open_cache(path)
            call = position_call(100)
            cache.store(call, "0x" + "00" * (3 * 32))
            before = cache.audit()
            self.assertEqual(before["cache_entries"], 1)
            self.assertEqual(before["progress_rows"], 0)
            rpc = FakeRpc()
            session = CachedArchiveSession(rpc, cache, CONTRACT)
            session.execute(call)
            self.assertEqual(rpc.calls, 0)
            self.assertEqual(session.cache_hits, 1)
            after = cache.audit()
            self.assertEqual(after["checkpoint_contiguous_through"], 0)
            self.assertEqual(after["progress_rows"], 1)
            cache.close()

    def test_identity_mismatch_fails_closed(self) -> None:
        with test_database() as path:
            cache = self.open_cache(path)
            cache.close()
            with self.assertRaises(CacheIdentityError):
                self.open_cache(path, identity("cc" * 32))

    def test_corruption_is_reported(self) -> None:
        with test_database() as path:
            cache = self.open_cache(path)
            session = CachedArchiveSession(FakeRpc(), cache, CONTRACT)
            session.execute(position_call(100))
            cache.close()
            connection = sqlite3.connect(path)
            connection.execute("UPDATE rpc_cache SET result_hex='0x12'")
            connection.commit()
            connection.close()
            cache = self.open_cache(path)
            audit = cache.audit()
            self.assertEqual(audit["invalid_entries"], 1)
            cache.close()


if __name__ == "__main__":
    unittest.main()
