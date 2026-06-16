from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting

PUBLIC_PIN_CREATION_KEY = "public_pin_creation"


async def is_public_pin_creation(db: AsyncSession) -> bool:
    setting = await db.get(Setting, PUBLIC_PIN_CREATION_KEY)
    if setting is None:
        return True
    return setting.value.strip().lower() in ("1", "true", "yes", "on")


async def set_public_pin_creation(db: AsyncSession, enabled: bool) -> None:
    setting = await db.get(Setting, PUBLIC_PIN_CREATION_KEY)
    value = "1" if enabled else "0"
    if setting is None:
        db.add(Setting(key=PUBLIC_PIN_CREATION_KEY, value=value))
    else:
        setting.value = value
    await db.commit()
