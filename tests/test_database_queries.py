from finance_bot.database import queries


class FakePool:
    def __init__(self):
        self.sql = ""

    async def fetchrow(self, sql, *_args):
        self.sql = sql
        return {"id": 1, "needs_review": True}


async def test_note_only_patch_does_not_clear_review(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(queries, "get_pool", lambda: pool)

    updated = await queries.patch_operation(1, {"note": "личная пометка"})

    assert "needs_review = 0" not in pool.sql
    assert updated["needs_review"] is True


async def test_regular_patch_still_clears_review(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(queries, "get_pool", lambda: pool)

    await queries.patch_operation(1, {"comment": "уточнено"})

    assert "needs_review = 0" in pool.sql
