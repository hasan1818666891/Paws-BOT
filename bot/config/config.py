from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str

    SLEEP_TIME: list[int] = [41200, 43200] #wait 12 hours
    START_DELAY: list[int] = [5, 25]
    
    AUTO_TASK: bool = True
    JOIN_TG_CHANNELS: bool = False
    AUTO_ADD_WALLET: bool = False
    
    REF_ID: str = 'acAO24ki'
    DISABLED_TASKS: list[str] = ['invite', 'boost']


settings = Settings()
