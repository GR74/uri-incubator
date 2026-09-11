import sqlalchemy as sa


async def test_first_migration_enables_postgres_extensions(db_engine) -> None:
    async with db_engine.connect() as connection:
        names = set(
            (
                await connection.execute(
                    sa.text(
                        "SELECT extname FROM pg_extension "
                        "WHERE extname IN ('vector', 'pgcrypto')"
                    )
                )
            ).scalars()
        )
    assert names == {"vector", "pgcrypto"}
