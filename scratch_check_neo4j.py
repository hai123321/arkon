import asyncio
from app.services.neo4j_service import neo4j_service

async def main():
    await neo4j_service.connect()
    try:
        async with neo4j_service._driver.session() as s:
            # Delete orphaned chunks
            res_ch = await s.run("MATCH (ch:Chunk) WHERE NOT (ch)-[:PART_OF]->() DETACH DELETE ch RETURN count(ch) as cnt")
            ch_record = await res_ch.single()
            print(f"Deleted orphaned chunks: {ch_record['cnt']}")
            
            # Delete orphaned entities
            res_e = await s.run("MATCH (e:Entity) WHERE NOT (e)-[:MENTIONED_IN]->() DETACH DELETE e RETURN count(e) as cnt")
            e_record = await res_e.single()
            print(f"Deleted orphaned entities: {e_record['cnt']}")
            
            c = await s.run('MATCH (n:Entity) RETURN count(n) as cnt')
            record = await c.single()
            print(f"Remaining Entity count: {record['cnt']}")
    finally:
        await neo4j_service.close()

if __name__ == "__main__":
    asyncio.run(main())
