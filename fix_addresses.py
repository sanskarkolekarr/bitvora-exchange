import asyncio
import os
import sys

# Add backend directory to module search path so app imports work
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.setting import Setting
from sqlalchemy import select

async def update_missing_addresses():
    print("Connecting to Supabase to inject missing addresses...")
    
    # Load all local chains from settings
    chains = settings.chains_list
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Setting))
        db_settings = result.scalars().all()
        
        updated_count = 0
        
        for chain in chains:
            key = f"{chain.upper()}_ADDRESS"
            local_val = getattr(settings, f"DEPOSIT_ADDRESS_{chain.upper()}", "")
            
            if not local_val:
                print(f"Skipping {key} because it's empty in local .env")
                continue
                
            # Find the row in DB
            found = False
            for db_setting in db_settings:
                if db_setting.key == key:
                    found = True
                    if db_setting.value_str == "MISSING_ADDRESS":
                        db_setting.value_str = local_val
                        print(f"✅ Replaced MISSING_ADDRESS for {key} with {local_val}")
                        updated_count += 1
                    break
            
            if not found:
                new_setting = Setting(key=key, value_str=local_val, value_float=0.0)
                session.add(new_setting)
                print(f"✅ Inserted new setting {key} = {local_val}")
                updated_count += 1
                
        if updated_count > 0:
            await session.commit()
            print(f"\n🎉 Successfully saved {updated_count} deposit addresses to Supabase!")
        else:
            print("\n✔️ No MISSING_ADDRESS found in DB. Everything looks okay!")

if __name__ == "__main__":
    asyncio.run(update_missing_addresses())
