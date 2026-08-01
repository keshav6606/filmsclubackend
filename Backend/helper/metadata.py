import asyncio
import PTN
from Backend.helper.imdb import get_detail, get_season, search_title
from Backend.helper.pyro import extract_tmdb_id, normalize_languages, clean_movie_title
from themoviedb import aioTMDb
from Backend.config import Telegram
import Backend
from Backend.logger import LOGGER
import traceback


import re
from typing import Union, Tuple, Optional

DELAY = 2

tmdb = aioTMDb(key=Telegram.TMDB_API, language="en-US", region="US")


def extract_season_and_episode(cleaned_filename: str, parsed: dict) -> Tuple[Optional[int], Optional[Union[int, str]]]:
    season = parsed.get('season')
    episode = parsed.get('episode')

    # Resolve season
    if isinstance(season, list):
        season = season[0] if season else None

    if season is None:
        season_match = re.search(r'(?i)\bS(?:eason)?\s*0*(\d+)\b', cleaned_filename)
        if season_match:
            season = int(season_match.group(1))

    # Check for explicit episode range regex patterns in cleaned_filename
    range_patterns = [
        r'(?i)\bS?\d*[\s._-]*E(?:pisode)?\s*0*(\d+)[\s._-]*(?:-|_|to|~|&|\s)+E?(?:pisode)?\s*0*(\d+)\b',
        r'(?i)\bE(?:pisode)?\s*0*(\d+)[\s._-]*(?:-|_|to|~|&|\s)+E?(?:pisode)?\s*0*(\d+)\b',
        r'(?i)\b(?:Ep|Episode|E)\s*0*(\d+)[\s._-]*(?:-|_|to|~|&|\s)+0*(\d+)\b(?:\s*(?:all|combined|episodes|480p|720p|1080p|hevc|hdrip|web-dl))?',
        r'(?i)\b0*(\d+)[\s._-]*(?:-|_|to)[\s._-]*0*(\d+)[\s._-]*(?:all|combined|episodes)\b',
    ]

    detected_range = None
    for pattern in range_patterns:
        match = re.search(pattern, cleaned_filename)
        if match:
            start_ep = int(match.group(1))
            end_ep = int(match.group(2))
            if 0 < start_ep < end_ep:
                detected_range = (start_ep, end_ep)
                break

    if detected_range:
        start_ep, end_ep = detected_range
        return season, f"{start_ep}-{end_ep}"

    # If PTN returned episode as a list e.g. [1, 9] or [1, 2, 3, 4, 5, 6, 7, 8, 9]
    if isinstance(episode, list):
        if len(episode) > 0:
            min_ep = min(episode)
            max_ep = max(episode)
            if min_ep < max_ep:
                return season, f"{min_ep}-{max_ep}"
            else:
                return season, min_ep
        else:
            episode = None

    if episode is not None:
        return season, episode

    # Single episode regex fallback if PTN missed it
    single_match = re.search(r'(?i)\bE(?:pisode)?\s*0*(\d+)\b', cleaned_filename)
    if single_match:
        return season, int(single_match.group(1))

    # General "Combined" or "All Episodes" without numbers
    if any(kw in cleaned_filename.lower() for kw in ['combined', 'all episodes', 'complete season', 'full season', 'zip', 'batch']):
        return season, "Combined"

    return season, None


def generate_seo_metadata(title: str, year: int, genres: list, languages: list, media_type: str, quality: str = None, rip: str = None) -> Tuple[str, list]:
    media_label = "TV Show" if media_type == "tv" else "Movie"
    quality_label = quality or "1080p"
    lang_str = ", ".join(languages) if languages else "Hindi"
    from Backend.helper.pyro import get_language_short_codes
    short_codes = get_language_short_codes(languages)
    short_codes_str = "/".join(short_codes) if short_codes else "HI"

    seo_title = f"Watch {title} ({year}) [{short_codes_str}] Online - Download {quality_label} {media_label}"

    keywords = [
        title,
        f"Watch {title} online",
        f"Download {title} {year}",
        f"{title} {quality_label}",
        f"{title} {media_label}",
        f"{title} {lang_str}",
        f"{title} {short_codes_str}",
        "filmy4uhd",
        "movies reborn",
        media_label,
        "Web Series" if media_type == "tv" else "Full Movie",
        "HD Download",
        "Free Stream"
    ]
    keywords.extend(languages or [])
    keywords.extend(short_codes)

    if genres:
        keywords.extend(genres)

    if any(k.lower() in title.lower() for k in ['drama', 'korean', 'kdrama', 'k-drama']):
        keywords.extend(["Kdrama", "Korean Series"])

    if any(k.lower() in title.lower() or 'animation' in [g.lower() for g in (genres or [])] for k in ['anime', 'naruto', 'attack', 'jujutsu', 'demon']):
        keywords.extend(["Anime", "Anime Series"])

    unique_keywords = list(dict.fromkeys(keywords))
    return seo_title, unique_keywords


async def metadata(filename: str, media) -> dict:
    try:
        # PTN.parse() से पहले filename साफ करें — URL, @channel, branding सब हटाएँ
        cleaned_filename = clean_movie_title(filename)
        LOGGER.debug(f"Raw filename: '{filename}' → Cleaned: '{cleaned_filename}'")
        parsed = PTN.parse(cleaned_filename)

        title = parsed.get('title')
        season, episode = extract_season_and_episode(cleaned_filename, parsed)
        year = parsed.get('year')
        quality = parsed.get('resolution')
        languages = normalize_languages(parsed.get('language'), filename)
        rip = parsed.get('quality')

        try:
            default_id = extract_tmdb_id(Backend.USE_DEFAULT_ID)
        except Exception as e:
            LOGGER.debug(f"Failed to extract default TMDB ID from USE_DEFAULT_ID: {e}")
            default_id = None

        if not default_id:
            try:
                default_id = extract_tmdb_id(filename)
            except Exception as e:
                LOGGER.debug(f"Failed to extract TMDB ID from filename {filename}: {e}")
                default_id = None

        is_tv_show = False
        tv_keywords = ['season', 'series', 'webseries', 'web series', 'episodes', 'episode', 'ep', 'kdrama', 'k-drama', 'anime', 'tvshow', 'show', 's0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9']
        
        if season is not None or any(kw in cleaned_filename.lower() for kw in tv_keywords):
            is_tv_show = True

        if title:
            if is_tv_show:
                if season is None:
                    season = 1
                if episode is None:
                    episode = "Full Season"
                LOGGER.info(f"Fetching TV metadata for: {title} S{season} Episode {episode}")
                return await fetch_tv_metadata(title, season, episode, year, quality, default_id, languages, rip)
            else:
                LOGGER.info(f"Fetching movie metadata for: {title} ({year})")
                res = await fetch_movie_metadata(title, year, quality, default_id, languages, rip)
                if res is None:
                    season = season or 1
                    episode = episode or "Full Season"
                    LOGGER.info(f"Movie fetch failed, trying TV metadata fallback for: {title}")
                    return await fetch_tv_metadata(title, season, episode, year, quality, default_id, languages, rip)
                return res

        LOGGER.info(f"No title parsed from: {filename} (parsed: {parsed})")
        return None

    except Exception as e:
        LOGGER.error(f"Unhandled error while parsing metadata for {filename}: {e}")
        return None




async def fetch_tv_metadata(title: str, season: int, episode: Union[int, str], year=None, quality=None, default_id=None, languages=None, rip=None) -> dict:
    try:
        tv_details, ep_details, use_tmdb = None, None, False
        imdb_id = default_id if default_id and default_id.startswith("tt") else None

        # Parse numeric episode for API detail fetching
        ep_nums = re.findall(r'\d+', str(episode))
        fetch_ep_id = int(ep_nums[0]) if ep_nums else 1

        is_combined = False
        if isinstance(episode, str) and ('-' in episode or 'to' in episode or 'Combined' in episode or 'all' in episode.lower()):
            is_combined = True

        if not imdb_id:
            result = await search_title(query=f"{title} {year}" if year else title, type="tvSeries")
            imdb_id = result['id'] if result else None

        if imdb_id:
            try:
                await asyncio.sleep(DELAY)
                tv_details = await get_detail(imdb_id=imdb_id)
                await asyncio.sleep(DELAY)
                ep_details = await get_season(imdb_id=imdb_id, season_id=season, episode_id=fetch_ep_id)
            except Exception as e:
                LOGGER.warning(f"IMDb TV fetch failed for ID {imdb_id}: {e}")
                tv_details, ep_details = None, None

        if not tv_details:
            use_tmdb = True
            await asyncio.sleep(DELAY)
            tmdb_results = await tmdb.search().tv(query=title)
            if not tmdb_results:
                LOGGER.warning(f"No TMDb results found for title '{title}'")
                return None
            tv_id = tmdb_results[0].id
            LOGGER.debug(f"TMDb ID found: {tv_id}")
            tv_details = await tmdb.tv(tv_id).details()
            try:
                ep_details = await tmdb.episode(tv_id, season, fetch_ep_id).details()
            except Exception as e:
                LOGGER.warning(f"TMDb episode details fetch failed for S{season}E{fetch_ep_id}: {e}")
                ep_details = None
        elif not ep_details:
            try:
                tmdb_results = await tmdb.search().tv(query=title)
                if tmdb_results:
                    tv_id = tmdb_results[0].id
                    ep_details = await tmdb.episode(tv_id, season, fetch_ep_id).details()
            except Exception as e:
                LOGGER.warning(f"TMDb fallback episode fetch failed: {e}")
                ep_details = None

        if use_tmdb:
            tmdb_id = tv_details.id
            show_title = tv_details.name
            show_year = tv_details.first_air_date.year if tv_details.first_air_date else 0
            rate = tv_details.vote_average or 0
            description = tv_details.overview or ''
            total_seasons = tv_details.number_of_seasons or 0
            total_episodes = tv_details.number_of_episodes or 0
            poster = f"https://image.tmdb.org/t/p/w500{tv_details.poster_path}" if tv_details.poster_path else ''
            backdrop = f"https://image.tmdb.org/t/p/original{tv_details.backdrop_path}" if tv_details.backdrop_path else ''
            status = tv_details.status or 'Unknown'
            genres = [genre.name for genre in tv_details.genres] if tv_details.genres else []
            if is_combined:
                ep_title = f"Episode {episode} Combined"
            else:
                ep_title = ep_details.name if ep_details and hasattr(ep_details, 'name') else f"S{season}E{episode}"
            ep_backdrop = f"https://image.tmdb.org/t/p/original{ep_details.still_path}" if ep_details and hasattr(ep_details, 'still_path') and ep_details.still_path else backdrop
        else:
            tmdb_id = tv_details['id'].replace("tt", "")
            show_title = tv_details.get('title', title)
            show_year = tv_details.get('releaseDetailed', {}).get('year', 0)
            rate = tv_details.get('rating', {}).get('star', 0)
            description = tv_details.get('plot', '')
            total_seasons = len(tv_details.get('all_seasons', []))
            total_episodes = sum(len(season.get('episodes', [])) for season in tv_details.get('seasons', []))
            poster = tv_details.get('image', '')
            backdrop = ''
            genres = tv_details.get('genre', [])
            if is_combined:
                ep_title = f"Episode {episode} Combined"
            else:
                ep_title = ep_details.get('title', f"S{season}E{episode}") if ep_details else f"S{season}E{episode}"
            ep_backdrop = ep_details.get('image', '') if ep_details else poster
            try:
                await asyncio.sleep(DELAY)
                fallback_results = await tmdb.search().tv(query=show_title)
                if fallback_results:
                    fallback_id = fallback_results[0].id
                    fallback_detail = await tmdb.tv(fallback_id).details()
                    backdrop = f"https://image.tmdb.org/t/p/original{fallback_detail.backdrop_path}" if fallback_detail.backdrop_path else ''
                    status = fallback_detail.status or 'Unknown'
                else:
                    status = 'Unknown'
            except Exception as e:
                LOGGER.warning(f"Fallback TMDb metadata fetch failed: {e}")
                status = 'Unknown'

        seo_title, keywords = generate_seo_metadata(show_title, show_year, genres, languages or ['hi'], "tv", quality, rip)

        result = {
            "tmdb_id": tmdb_id,
            "title": show_title,
            "year": show_year,
            "rate": rate,
            "description": description,
            "total_seasons": total_seasons,
            "total_episodes": total_episodes,
            "poster": poster,
            "backdrop": backdrop,
            "status": status,
            "genres": genres,
            "media_type": "tv",
            "season_number": season,
            "episode_number": episode,
            "episode_title": ep_title,
            "episode_backdrop": ep_backdrop,
            "quality": quality,
            "languages": languages or ['hi'],
            "rip": rip or 'Blu-ray',
            "keywords": keywords,
            "seo_title": seo_title
        }

        LOGGER.info(f"Metadata successfully fetched for {show_title} S{season} Episode {episode}")
        return result

    except Exception as e:
        LOGGER.error(f"Error fetching TV metadata for '{title}' S{season} Episode {episode}: {e}", exc_info=True)
        return None

    except Exception as e:
        LOGGER.error(f"Error fetching TV metadata for '{title}' S{season} Episode {episode}: {e}", exc_info=True)
        return None




async def fetch_movie_metadata(title: str, year=None, quality=None, default_id=None, languages=None, rip=None) -> dict:
    try:
        movie_details, use_tmdb = None, False
        imdb_id = default_id if default_id and default_id.startswith("tt") else None

        if not imdb_id:
            try:
                result = await search_title(query=f"{title} {year}" if year else title, type="movie")
                imdb_id = result['id'] if result else None
                
            except Exception as e:
                LOGGER.warning(f"IMDb search failed for '{title}': {e}")
                imdb_id = None

        if imdb_id:
            try:
                clean_id = imdb_id[2:] if imdb_id.startswith("tt") else imdb_id
                LOGGER.debug(f"Fetching IMDb details using ID: {clean_id}")
                movie_details = await get_detail(imdb_id=clean_id)
               
            except Exception as e:
                LOGGER.warning(f"IMDb movie fetch failed for '{title}': {e}")
                movie_details = None

        if not movie_details:
            use_tmdb = True
            try:
                tmdb_results = await tmdb.search().movies(query=title, year=year) if year else await tmdb.search().movies(query=title)
                if not tmdb_results:
                    LOGGER.warning(f"No TMDB results found for '{title}'")
                    return None
                movie_id = tmdb_results[0].id
                movie_details = await tmdb.movie(movie_id).details()
            except Exception as e:
                LOGGER.error(f"TMDB search failed for '{title}': {e}")
                return None

        if use_tmdb:
            tmdb_id = movie_details.id
            movie_title = movie_details.title
            movie_year = movie_details.release_date.year if movie_details.release_date else 0
            rate = movie_details.vote_average or 0
            description = movie_details.overview or ''
            poster = f"https://image.tmdb.org/t/p/w500{movie_details.poster_path}" if movie_details.poster_path else ''
            backdrop = f"https://image.tmdb.org/t/p/original{movie_details.backdrop_path}" if movie_details.backdrop_path else ''
            runtime = movie_details.runtime or 0
            genres = [genre.name for genre in movie_details.genres] if movie_details.genres else []
        else:
            description = movie_details.get('plot', '')
            tmdb_id = movie_details['id'].replace("tt", "")
            movie_title = movie_details.get('title', title)
            movie_year = movie_details.get('releaseDetailed', {}).get('year', 0)
            rate = movie_details.get('rating', {}).get('star', 0)
            runtime = movie_details.get('runtimeSeconds', 0) // 60
            genres = movie_details.get('genre', [])
            try:
                force_tmdb_results = await tmdb.search().movies(query=movie_title, year=movie_year)
                force_movie_id = force_tmdb_results[0].id
                force_movie_details = await tmdb.movie(force_movie_id).details()
                backdrop = f"https://image.tmdb.org/t/p/original{force_movie_details.backdrop_path}" if force_movie_details.backdrop_path else ''
                poster = movie_details.get('image', '') or \
                         (f"https://image.tmdb.org/t/p/w500{force_movie_details.poster_path}" if force_movie_details.poster_path else '')
            except Exception as e:
                backdrop = ''
                poster = ''

        seo_title, keywords = generate_seo_metadata(movie_title, movie_year, genres, languages or ['hi'], "movie", quality, rip)

        LOGGER.info(f"Metadata fetched successfully for '{movie_title}' ({movie_year})")
        return {
            "tmdb_id": tmdb_id,
            "title": movie_title,
            "year": movie_year,
            "rate": rate,
            "description": description,
            "poster": poster,
            "backdrop": backdrop,
            "media_type": "movie",
            "genres": genres,
            "runtime": runtime,
            "quality": quality,
            "languages": languages or ['hi'],
            "rip": rip or 'Blu-ray',
            "keywords": keywords,
            "seo_title": seo_title
        }

    except Exception as e:
        LOGGER.error(f"Unhandled error in fetch_movie_metadata for '{title}': {e}")
        return None

        
