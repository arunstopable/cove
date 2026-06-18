"""
Module for parsing and rewriting M3U8 HLS playlists from Vixcloud.
"""

import re
import urllib.parse


def rewrite_master_m3u8(original_m3u8: str, proxy_base_url: str, title_id: int, is_fhd: bool = True) -> str:
    """
    Parses the master playlist and rewrites child stream URLs (video, audio, sub)
    to point back to this proxy server using relative paths.

    Also filters out lower resolution streams, keeping ONLY the highest available
    resolution (e.g., 1080p if available, otherwise 720p).
    If is_fhd is False, it caps the maximum resolution at 720p to avoid 403 Forbidden.
    """
    lines = original_m3u8.splitlines()
    rewritten_lines = []

    max_height = 0
    stream_blocks = []
    current_block = []

    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF"):
            current_block = [line]
        elif current_block and not line.startswith("#"):
            current_block.append(line)
            stream_blocks.append(current_block)
            current_block = []

            # Extract resolution height from EXTF-X-STREAM-INF
            res_match = re.search(r"RESOLUTION=\d+x(\d+)", stream_blocks[-1][0])
            if res_match:
                height = int(res_match.group(1))
                if not is_fhd and height > 720:
                    continue
                if height > max_height:
                    max_height = height
        else:
            if not current_block:
                rewritten_lines.append(line)

    if max_height > 0:
        for block in stream_blocks:
            res_match = re.search(r"RESOLUTION=\d+x(\d+)", block[0])
            if res_match and int(res_match.group(1)) == max_height:
                info_line, url_line = block
                info_line = re.sub(r',?SUBTITLES="[^"]+"', '', info_line)
                rewritten_lines.append(info_line)
                enc_url = urllib.parse.quote(url_line, safe="")
                proxy_url = f"{proxy_base_url}/proxy_child.m3u8?title_id={title_id}&child_url={enc_url}"
                rewritten_lines.append(proxy_url)
    else:
        for block in stream_blocks:
            info_line, url_line = block
            info_line = re.sub(r',?SUBTITLES="[^"]+"', '', info_line)
            rewritten_lines.append(info_line)
            enc_url = urllib.parse.quote(url_line, safe="")
            proxy_url = f"{proxy_base_url}/proxy_child.m3u8?title_id={title_id}&child_url={enc_url}"
            rewritten_lines.append(proxy_url)

    # Rewrite Audio media definitions and filter out Subtitles
    final_lines = []
    for line in rewritten_lines:
        if line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES"):
            continue  # Drop subtitles to prevent ffmpeg MKV muxer crashes
        if line.startswith("#EXT-X-MEDIA:"):
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                orig_uri = uri_match.group(1)
                enc_uri = urllib.parse.quote(orig_uri, safe="")
                new_uri = f"{proxy_base_url}/proxy_child.m3u8?title_id={title_id}&child_url={enc_uri}"
                line = line.replace(f'URI="{orig_uri}"', f'URI="{new_uri}"')
        final_lines.append(line)

    return "\n".join(final_lines) + "\n"


def rewrite_child_m3u8(original_m3u8: str, child_url: str, proxy_base_url: str) -> str:
    """
    Parses a child playlist (video, audio, or subtitle).
    - Resolves relative TS segment paths to absolute URLs.
    - Intercepts EXT-X-KEY to proxy the AES-128 encryption key using relative paths.
    - Routes .ts segments through /segment.ts proxy using relative paths.
    """
    # child_url looks like: https://vixcloud.co/playlist/.../chunk.m3u8?...
    base_url = child_url.split("?")[0].rsplit("/", 1)[0] + "/"

    lines = original_m3u8.splitlines()
    rewritten_lines = []

    for line in lines:
        if line.startswith("#EXT-X-KEY:"):
            # Intercept AES encryption key requests
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                orig_key_uri = uri_match.group(1)
                enc_key_uri = urllib.parse.quote(orig_key_uri, safe="")
                new_key_uri = f"{proxy_base_url}/enc.key?key_url={enc_key_uri}"
                line = line.replace(f'URI="{orig_key_uri}"', f'URI="{new_key_uri}"')
            rewritten_lines.append(line)

        elif line.startswith("#") or not line.strip():
            rewritten_lines.append(line)
        else:
            # It's a segment URL. Resolve if relative.
            if not line.startswith("http"):
                line = urllib.parse.urljoin(base_url, line)
            rewritten_lines.append(line)

    return "\n".join(rewritten_lines) + "\n"
