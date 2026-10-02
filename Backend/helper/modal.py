from datetime import datetime
from pydantic import BaseModel, Field, ValidationError
try:
    from pydantic import field_validator
    def before_validator(field_name):
        return field_validator(field_name, mode="before")
except ImportError:
    from pydantic import validator
    def before_validator(field_name):
        return validator(field_name, pre=True, always=True)
from typing import List, Optional, Union, Dict

class QualityDetail(BaseModel):
    quality: Optional[str] = Field(default="HD", description="Quality of the video (e.g., 1080p, 720p)")
    id: str = Field(..., description="Unique hash for the video")
    name: str = Field(default="video.mkv", description="Original Filename of telegram file")
    size: str = Field(default="Unknown", description="Size of the File")
    language: Optional[str] = Field(None, description="Language of this specific file (e.g., Hindi, English, Dual Audio)")

    @before_validator("quality")
    @classmethod
    def clean_quality(cls, v):
        if not v or not str(v).strip() or str(v).lower() in ["none", "null"]:
            return "HD"
        return str(v).strip()

    @before_validator("name")
    @classmethod
    def clean_name(cls, v):
        if not v or not str(v).strip():
            return "video.mkv"
        return str(v).strip()

    @before_validator("size")
    @classmethod
    def clean_size(cls, v):
        if not v or not str(v).strip():
            return "Unknown"
        return str(v).strip()

class Episode(BaseModel):
    episode_number: Union[int, str] = Field(..., description="Episode number within the season")
    title: Optional[str] = Field(default="Episode", description="Title of the episode")
    episode_backdrop: Optional[str] = Field(default="", description="Backdrop of Episode")
    telegram: Optional[List[QualityDetail]] = Field(None, description="List of available quality details")
    channel_message_id: Optional[int] = Field(None, description="Telegram message ID of the channel post")
    channel_message_ids: Optional[Dict[str, int]] = Field(default_factory=dict, description="Telegram message IDs per channel")

class Season(BaseModel):
    season_number: int = Field(..., description="Season number within the TV show")
    episodes: List[Episode] = Field(..., description="List of episodes in the season")

class TVShowSchema(BaseModel):
    tmdb_id: int = Field(..., description="The TMDB ID of the TV show")
    title: str = Field(..., description="Title of the TV show")
    genres: Optional[List[str]] = Field(default_factory=list, description="List of genres associated with the TV show")
    description: Optional[str] = Field(default="", description="Brief description of the TV show")
    rating: Optional[float] = Field(default=0.0, description="Average rating of the TV show")
    release_year: Optional[int] = Field(default=0, description="Release year of the TV show")
    poster: Optional[str] = Field(default="", description="URL to the poster image")
    backdrop: Optional[str] = Field(default="", description="URL to the backdrop image")
    total_seasons: Optional[int] = Field(default=1, description="Total Season of tv show")
    total_episodes: Optional[int] = Field(default=1, description="Total Episode of tv show")
    media_type: str = Field(default="tv", description="Media Type of the file")
    status: Optional[str] = Field(default="Returning Series", description="Status update of tv show")
    updated_on: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the last update")
    languages: Optional[List[str]] = Field(default_factory=lambda: ["Hindi"], description="List of languages associated with the Movie")
    rip: Optional[str] = Field(default="Blu-ray", description="Media rip of the file")
    keywords: Optional[List[str]] = Field(default_factory=list, description="SEO Keywords and tags")
    seo_title: Optional[str] = Field(None, description="SEO Title")
    seasons: List[Season] = Field(default_factory=list, description="List of seasons in the TV show")

class MovieSchema(BaseModel):
    tmdb_id: int = Field(..., description="The TMDB ID of the Movie")
    title: str = Field(..., description="Title of the Movie")
    genres: Optional[List[str]] = Field(default_factory=list, description="List of genres associated with the Movie")
    description: Optional[str] = Field(default="", description="Brief description of the Movie")
    rating: Optional[float] = Field(default=0.0, description="Average rating of the Movie")
    release_year: Optional[int] = Field(default=0, description="Release year of the Movie")
    poster: Optional[str] = Field(default="", description="URL to the poster image")
    backdrop: Optional[str] = Field(default="", description="URL to the backdrop image")
    media_type: str = Field(default="movie", description="Media Type of the file")
    runtime: Optional[int] = Field(default=0, description="runtime of the movie")
    updated_on: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the last update")
    languages: Optional[List[str]] = Field(default_factory=lambda: ["Hindi"], description="List of languages associated with the Movie")
    rip: Optional[str] = Field(default="Blu-ray", description="Media rip of the file")
    keywords: Optional[List[str]] = Field(default_factory=list, description="SEO Keywords and tags")
    seo_title: Optional[str] = Field(None, description="SEO Title")
    telegram: Optional[List[QualityDetail]] = Field(None, description="List of available quality details")
    channel_message_id: Optional[int] = Field(None, description="Telegram message ID of the channel post")
    channel_message_ids: Optional[Dict[str, int]] = Field(default_factory=dict, description="Telegram message IDs per channel")