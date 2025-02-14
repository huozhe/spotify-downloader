from collections import defaultdict
from pathlib import Path
from typing import List

from spotdl.search import SongObject, song_gatherer
from spotdl.providers import (
    provider_utils,
    metadata_provider,
    ytm_provider,
)


def parse_query(
    query: List[str], format, use_youtube, generate_m3u, threads
) -> List[SongObject]:
    """
    Parse query and return list containing song object
    """

    songs_list = []

    # Iterate over all search queries and add them to songs_list
    for request in query:
        if request.endswith(".spotdlTrackingFile"):
            continue

        songs_list.extend(
            parse_request(request, format, use_youtube, generate_m3u, threads)
        )

        # linefeed to visually separate output for each query
        print()

    # remove duplicates
    seen_songs = set()
    songs = []
    for song in songs_list:
        if song.file_name not in seen_songs:
            songs.append(song)
            seen_songs.add(song.file_name)

    return songs


def parse_request(
    request: str,
    output_format: str = None,
    use_youtube: bool = False,
    generate_m3u: bool = False,
    threads: int = 1,
) -> List[SongObject]:
    song_list: List[SongObject] = []
    if (
        "youtube.com/watch?v=" in request
        and "open.spotify.com" in request
        and "track" in request
        and "|" in request
    ):
        urls = request.split("|")

        if len(urls) <= 1 or "youtube" not in urls[0] or "spotify" not in urls[1]:
            print("Incorrect format used, please use YouTubeURL|SpotifyURL")
        else:
            print("Fetching YouTube video with spotify metadata")
            song_list = [
                song
                for song in [get_youtube_meta_track(urls[0], urls[1], output_format)]
                if song is not None
            ]
    elif (
        "music.youtube.com/playlist?list=" in request
        and "open.spotify.com" in request
        and "|" in request
    ):
        urls = request.split("|")

        if len(urls) <= 1 or "youtube" not in urls[0] or "spotify" not in urls[1]:
            print("Incorrect format used, please use YouTubeMusicURL|SpotifyURL")
        else:
            print("Fetching YouTube Music playlist with spotify metadata")
            song_list = [
                song
                for song in get_youtube_meta_playlist(
                    urls[0], urls[1], output_format, generate_m3u, threads
                )
                if song is not None
            ]
    elif "open.spotify.com" in request and "track" in request:
        print("Fetching Song...")
        song = song_gatherer.from_spotify_url(request, output_format, use_youtube)
        try:
            song_list = [song] if song.youtube_link is not None else []
        except (OSError, ValueError, LookupError):
            song_list = []
    elif "open.spotify.com" in request and "album" in request:
        print("Fetching Album...")
        song_list = song_gatherer.from_album(
            request, output_format, use_youtube, generate_m3u, threads
        )
    elif "open.spotify.com" in request and "playlist" in request:
        print("Fetching Playlist...")
        song_list = song_gatherer.from_playlist(
            request, output_format, use_youtube, generate_m3u, threads
        )
    elif "open.spotify.com" in request and "artist" in request:
        print("Fetching artist...")
        song_list = song_gatherer.from_artist(
            request, output_format, use_youtube, threads
        )
    elif request == "saved":
        print("Fetching Saved Songs...")
        song_list = song_gatherer.from_saved_tracks(output_format, use_youtube, threads)
    else:
        print('Searching Spotify for song named "%s"...' % request)
        try:
            song_list = song_gatherer.from_search_term(
                request, output_format, use_youtube
            )
        except Exception as e:
            print(e)

    # filter out NONE songObj items (already downloaded)
    song_list = [song_object for song_object in song_list if song_object is not None]

    return song_list


def get_youtube_meta_track(
    youtube_url: str, spotify_url: str, output_format: str = None
):
    # check if URL is a playlist, user, artist or album, if yes raise an Exception,
    # else procede

    # Get the Song Metadata
    print(f"Gathering Spotify Metadata for: {spotify_url}")
    raw_track_meta, raw_artist_meta, raw_album_meta = metadata_provider.from_url(
        spotify_url
    )

    song_name = raw_track_meta["name"]
    contributing_artist = []
    for artist in raw_track_meta["artists"]:
        contributing_artist.append(artist["name"])

    converted_file_name = SongObject.create_file_name(
        song_name, [artist["name"] for artist in raw_track_meta["artists"]]
    )

    if output_format is None:
        output_format = "mp3"

    converted_file_path = Path(".", f"{converted_file_name}.{output_format}")

    # if a song is already downloaded skip it
    if converted_file_path.is_file():
        print(f'Skipping "{converted_file_name}" as it\'s already downloaded')
        return None

    # (try to) Get lyrics from Genius
    lyrics = provider_utils._get_song_lyrics(song_name, contributing_artist)

    return SongObject(
        raw_track_meta, raw_album_meta, raw_artist_meta, youtube_url, lyrics
    )


def get_youtube_meta_playlist(
    youtube_url: str,
    spotify_url: str,
    output_format: str = None,
    generate_m3u: bool = False,
    threads: int = 1,
):
    # get metadata for all the songs in the album from spotify
    print(f"Gathering Spotify Metadata for: {spotify_url}")
    song_list = song_gatherer.from_album(
        spotify_url, output_format, False, generate_m3u, threads, skip_youtube=True
    )

    def compute_diff(a, b):
        count_a = defaultdict(int)
        for c in "".join(a.split()):
            count_a[c] += 1
        count_b = defaultdict(int)
        for c in "".join(b.split()):
            count_b[c] += 1
        diff = sum(abs(count_a[k] - count_b[k]) for k in set(count_a) | set(count_b))
        return diff

    # get sound url from Youtube Music
    ytm_metadata = ytm_provider.get_metadata_for_playlist(youtube_url)
    ytm_titles = [song["title"] for song in ytm_metadata]
    if not ytm_titles:
        print(f"Can not find download links from Youtube Music for {youtube_url}")
        return []

    # find the best match
    for song in song_list:
        t = song.song_name
        diff_scores = [
            (compute_diff(t, yt), idx, yt) for (idx, yt) in enumerate(ytm_titles)
        ]
        best_match = min(diff_scores)
        diff_score, best_idx, yt_title = best_match
        if diff_score:  # mismatch
            print(
                "Best match between Spotify and YTM are not identical. "
                "Spotify: {}, YTM: {}, diff_score: {}".format(t, yt_title, diff_score)
            )
        song._youtube_link = "https://www.youtube.com/watch?v={}".format(
            ytm_metadata[best_idx]["videoId"]
        )
        print("DEBUG: {} : {} : {}".format(t, best_match, song._youtube_link))

    return song_list
