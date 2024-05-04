from asyncio.subprocess import create_subprocess_shell, PIPE
from aiofiles.ospath import exists
from aiofiles.os import mkdir
import aiofiles
from aiohttp import ClientSession as Client
from ._handler import new_cmd, newCall, auth_only
from telethon import Button
from ._config import OWNER_ID
from aiofiles.os import remove


COMMAND_FOR_DL = "yt-dlp --downloader aria2c '{url}'"
SERIES_BACKEND_URL = "https://6301-2-59-134-198.ngrok-free.app"
SERVIO_TEMP = "https://243eecbf48fe111a73868d2a4d6ea7fa.serveo.net"

async def file_server():
    from aiohttp import web
    import os

    async def handle(request):
        path = request.match_info.get('path', '')
        if os.path.isfile(path):
            return web.FileResponse(os.path.join(os.getcwd(), "downloads", path))
        else:
            return web.FileResponse(os.path.join(os.getcwd(), "downloads", path))
        
    app = web.Application()
    app.router.add_get('/{path:.*}', handle)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 2002)
    await site.start()


async def search_series(query: str, client: Client):
    async with client.get(f"{SERIES_BACKEND_URL}/api/search", params={"query": query}) as resp:
        return (await resp.json()).get("titles", [])


def get_id_from_href(href: str):
    return href.split("-")[-1]


async def get_seasons(series_id: str, client: Client):
    series_id = get_id_from_href(series_id)

    print(f"{SERIES_BACKEND_URL}/api/seasons?id={series_id}")
    async with client.get(f"{SERIES_BACKEND_URL}/api/seasons?id={series_id}") as resp:
        return await resp.json()


async def get_episodes(series_id: str, season_id: str, client: Client):
    series_id = get_id_from_href(series_id)
    async with client.get(f"{SERIES_BACKEND_URL}/api/episodes?id={season_id}") as resp:
        return await resp.json()


async def get_embed(media_id: str, category: str, client: Client):
    print(f"{SERIES_BACKEND_URL}/api/embed?id={media_id}&cat={category.lower()}")
    async with client.get(f"{SERIES_BACKEND_URL}/api/embed", params={"id": media_id, "cat": category.lower()}) as resp:
        try:
            resp = await resp.json()
            source_hash = resp.get("source_hash")

            if not source_hash:
                return None

            print(f"{SERIES_BACKEND_URL}/{source_hash}")
            async with client.get(f"{SERIES_BACKEND_URL}/{source_hash}") as source_resp:
                return await source_resp.json()

        except:

            return None

series_meta_cache = {}


@new_cmd(pattern="series")
async def search_series_x(e):
    try:
        q = e.text.split(" ", 1)[1]
    except IndexError:
        return await e.reply("Give me a query.")

    async with Client() as client:
        titles = await search_series(q, client)
        if not titles:
            return await e.reply("No results found.")

        buttons = []
        for title in titles:
            buttons.append([Button.inline(title["title"], data=f"series_{get_id_from_href(title['href'])}")])
            series_meta_cache[get_id_from_href(title["href"])] = title

            if len(buttons) == 15:
                break

        await e.reply("Choose a series:", buttons=buttons, file="https://envs.sh/eET.png", force_document=True)

m3u8_cache = {}


@newCall(pattern="series_(.*)")
async def series_x(e):
    series_id = e.data.decode().split("_", 1)[1]

    async with Client() as client:
        try:
            series = series_meta_cache[series_id]
        except KeyError:
            return await e.edit("Series not found.")

        if series.get("category") == "Movie":
            src = await get_embed(series_id, series["category"], client)
            if src is None:
                return await e.edit("Failed to get source.")

            await e.edit(f"**M3U8:** \n`{src['file']}`", buttons=[[Button.inline("Download", data=f"dl_{src['id']}")]], file=(SERIES_BACKEND_URL + series["poster"]).replace("184x275", "500x750"))
            m3u8_cache[src["id"]] = src["file"]
            return

        seasons = await get_seasons(series_id, client)

        buttons = []
        for season in seasons:
            buttons.append([Button.inline(season["title"], data=f"season_{series_id}_{season['season_id']}_{series['category']}_{len(buttons)+1}")])

        buttons.append([Button.inline("Back", data="back")])

        await e.edit(f"Choose a season for {series['title']}:", buttons=buttons, file=(SERIES_BACKEND_URL + series["poster"]).replace("184x275", "500x750"))


@newCall(pattern="season_(.*)")
async def season_x(e):
    series_id, season_id, category, season_index = e.data.decode().split("_", 4)[
        1:]

    async with Client() as client:
        episodes = await get_episodes(series_id, season_id, client)

        buttons = []
        for episode in episodes:
            buttons.append([Button.inline(episode["title"], data=f"episode_{series_id}_{season_id}_{episode['episode_id']}_{category}_{season_index}_{len(buttons)+1}")])

        buttons.append([Button.inline("Download All", data=f"download_all")])
        buttons.append([Button.inline("Back", data=f"series_{series_id}")])

        await e.edit(f"Choose an episode for {series_meta_cache[series_id]['title']}:", buttons=buttons)


@newCall(pattern="episode_(.*)")
async def episode_x(e):
    series_id, season_id, episode_id, category, season_index, episode_index = e.data.decode().split("_",
                                                                                                    6)[1:]

    async with Client() as client:
        src = await get_embed(episode_id, category, client)
        if src is None:
            return await e.edit("Failed to get source.")
        tick_emoji = "✅"

        await e.edit(f"**Source Avaliable {tick_emoji}**\n\n**SUBS: {', '.join([sub['label'] for sub in src['subs']])}**",
                     buttons=[[Button.inline("Download", data=f"dl_{src['id']}_{category}_{season_index}_{episode_index}_{series_id}")],
                                [Button.inline("Back", data=f"season_{series_id}_{season_id}_{category}_{season_index}")]])
        m3u8_cache[src["id"]] = src
import os, time

def generate_ffmpeg_command(mp4_file_path, subs):
    ffmpeg_command = ['ffmpeg', '-i', '"{}"'.format(mp4_file_path)]

    for sub in subs:
        ffmpeg_command.extend(['-i', sub["file"]])

    output_file_path = '"{}"'.format(mp4_file_path.replace(".mkv", "_subs.mkv"))

    ffmpeg_command.extend(['-map', '0:v', '-map', '0:a'])

    for i in range(len(subs)):
        # ffmpeg_command.extend(['-map', f'{i + 1}:s:0', '-scodec', 'mov_text'])
        ffmpeg_command.extend(['-map', f'{i + 1}:s:0']) 
    ffmpeg_command.extend(['-c', 'copy'])
    ffmpeg_command.append(output_file_path)
    
    # add -y to overwrite the file
    ffmpeg_command.insert(1, "-y")

    return ffmpeg_command

@newCall(pattern="dl_(.*)")
async def download_x(e):
    _, media_id, category, season_index, episode_index, series_id = e.data.decode().split("_", 5)

    url_ = m3u8_cache.get(media_id)
    if not url_:
        return await e.edit("Invalid media ID.")
    
    url = url_["file"]
    
    subs_urls = url_["subs"]
    
    await e.edit("Downloading...")
    
    try:
        series = series_meta_cache[series_id]
    except KeyError:
        return await e.edit("Series not found.")

    out_folder = "downloads_temp"
    if not await exists(out_folder):
        await mkdir(out_folder)
    out_filename = f"{series['title']}_{category}_{season_index}_{episode_index}.mkv"
    await e.edit(f"Downloading {out_filename}...", buttons=[Button.inline("Back", data=f"series_{series_id}")])
    ms = await e.respond("Downloading...")
    t = time.time()
    cmd = f"yt-dlp --downloader aria2c '{url}' -o '{out_folder}/{out_filename}'"
    print("Command:", cmd)

    process = await create_subprocess_shell(
        cmd=cmd,
        stdout=PIPE,
        stderr=PIPE,
    )
    
    await process.wait()
    # merge all subs to the file
    
    ffmpeg_command = generate_ffmpeg_command(f"{out_folder}/{out_filename}", subs_urls)
    print("FFMPEG Command:", ffmpeg_command)
    await ms.edit("Merging subs...")
    (await create_subprocess_shell(" ".join(ffmpeg_command))).wait()
    
    # os.remove(f"{out_folder}/{out_filename}")
    await create_subprocess_shell(f"mv '{out_folder}/{out_filename.replace('.mkv', '_subs.mkv')}' downloads/").wait()
    
    await ms.edit(f"Downloaded {out_filename} in {time.time() - t:.2f} seconds.", buttons=[[Button.inline("Back", data=f"episode_{series_id}_{season_index}_{episode_index}_{category}_{season_index}_{episode_index}")],
                                                                                             [Button.url("Index Link", f"{SERVIO_TEMP}")]])
    await remove(f"{out_folder}/{out_filename}")
    
    # move the file to downloads folder
    
    
    
    
    
    
    
    
   

dl_all_queue = []

@newCall(pattern="download_all")
async def download_all(e):
    if e.sender_id != OWNER_ID and e.sender_id in dl_all_queue:
        await e.answer("You're already in the queue, wait for your turn.", alert=True)
        return
    msg = await e.get_message()

    buttons = msg.reply_markup.rows

    print(len(buttons))


def progress_stdout_yielded_downloadx(url, out_folder, out_filename):
    import os
    import subprocess
    import shlex

    cmd = f"youtube-dl -o '{out_folder}/{out_filename}' {url}"
    print(cmd)
    process = subprocess.Popen(shlex.split(
        cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while True:
        output = process.stdout.readline()
        if output == b'' and process.poll() is not None:
            break
        if output:
            yield output
    rc = process.poll()

    return rc


async def progress_stdout_yielded_download(url, out_folder, out_filename):
    if not await exists(out_folder):
        await mkdir(out_folder)

    cmd = f"yt-dlp --downloader aria2c '{url}' -o '{out_folder}/{out_filename}'"
    print("Command:", cmd)

    process = await create_subprocess_shell(
        cmd=cmd,
        stdout=PIPE,
        stderr=PIPE,
    )


    while True:
        output = await process.stdout.readline()  
        if output == b'' and process.returncode is not None:
            break
        if output:
            yield output.decode("utf-8")  

    rc = await process.wait() 

