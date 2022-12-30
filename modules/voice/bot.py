import asyncio
import itertools

import discord
from discord.ext import commands

from modules.voice.music_player import MusicPlayer
from modules.voice.ui import UI
from modules.voice.utils import get_duration
from modules.voice.yt import YTDLSource
from utils.command import command
from utils.errors import DiscordException


class Music(commands.GroupCog, group_name='voice'):

    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        self.uis = {}

    async def cleanup(self, guild):
        try:
            await guild.voice_client.disconnect()
        except AttributeError:
            pass

        if self.players.get(guild.id) is not None:
            del self.players[guild.id]

    async def __local_check(self, ctx):
        """A local check which applies to all commands in this cog."""
        if not ctx.guild:
            raise commands.NoPrivateMessage
        return True

    def get_player(self, ctx):
        try:
            player = self.players[ctx.guild.id]
        except KeyError:
            player = MusicPlayer(ctx, self.uis.get(ctx.guild.id))
            self.players[ctx.guild.id] = player

        return player

    def get_ui(self, ctx):
        return self.uis.get(ctx.guild.id)

    async def update_ui(self, ctx):
        ui = self.get_ui(ctx)
        if ui is not None:
            await ui.update()

    async def join(self, channel, vc):
        if vc:
            if vc.channel.id == channel.id:
                return
            try:
                await vc.move_to(channel)
            except asyncio.TimeoutError:
                raise DiscordException(f"Moving to channel: <{channel}> timed out.")
        else:
            try:
                await channel.connect()
            except asyncio.TimeoutError:
                raise DiscordException(
                    f"Connecting to channel: <{channel}> timed out."
                )

    async def search_and_play(self, ctx, search, count):
        sources = await self.search(ctx, search, count)
        return await self.play(sources)

    async def search(self, ctx, search, count):
        return await YTDLSource.create_source(ctx.author,
                                              search,
                                              loop=self.bot.loop,
                                              count=count)

    async def play(self, ctx, sources: list):
        player = self.get_player(ctx)
        asyncio.ensure_future(player.add_to_queue(sources))

        queue_str = '\n'.join([f"[{d['title']}]({d['webpage_url']})" for d in sources])
        embed = discord.Embed(
            title="",
            description=f"Queued\n {queue_str}\n[{ctx.author.mention}]",
            color=discord.Color.green(),
        )
        return embed

    ######################################################################################

    @command(
        name="join", description="connects to voice"
    )
    async def connect_(self, ctx, channel: discord.VoiceChannel = None):
        if not channel:
            try:
                channel = ctx.author.voice.channel
            except AttributeError:
                embed = discord.Embed(
                    title="",
                    description="No channel to join. Please call `,join` from a voice channel.",
                    color=discord.Color.red(),
                )
                await ctx.send(embed=embed)
                raise DiscordException(
                    "No channel to join. Please either specify a valid channel or join one."
                )

        vc = ctx.voice_client
        await self.join(channel, vc)
        embed = discord.Embed(
            title="Joined",
            description=f"Joined {channel.mention}",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)
        await self.update_ui(ctx)

    @command(name="play", description="streams music", long=True)
    async def play_(self, ctx, search: str, count=1):
        vc = ctx.voice_client

        if not vc:
            raise DiscordException("Need to join first")

        embed = await self.search_and_play(ctx, search, count)
        await ctx.send(embed=embed)
        await self.update_ui(ctx)

    @command(name="play_file", description="streams music", long=True)
    async def play_file_(self, ctx, attachment: discord.Attachment):
        vc = ctx.voice_client

        if not vc:
            raise DiscordException("Need to join first")
        if not attachment.content_type.startswith("audio"):
            raise DiscordException(f"Please upload audio file. (Invalid file type: `{attachment.content_type}`)")

        embed = await self.play(ctx, [{
            "webpage_url": attachment.url,
            "requester": ctx.author,
            "title": attachment.filename,
        }])
        await ctx.send(embed=embed)
        await self.update_ui(ctx)

    @command(
        name="shuffle", description="make mess in queue"
    )
    async def random_(self, ctx):
        vc = ctx.voice_client
        if not vc:
            await ctx.invoke(self.connect_)

        player = self.get_player(ctx)

        player.queue.shuffle()

        embed = discord.Embed(
            title="Queue",
            description="There is a slight mess in the queue. 🎲",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)
        await self.update_ui(ctx)

    @command(name="pause", description="pauses music")
    async def pause_(self, ctx):
        vc = ctx.voice_client

        if not vc or not vc.is_playing():
            embed = discord.Embed(
                title="",
                description="I am currently not playing anything",
                color=discord.Color.green(),
            )
            return await ctx.send(embed=embed)
        elif vc.is_paused():
            return

        vc.pause()
        embed = discord.Embed(
            title="Paused ⏸️",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)
        await self.update_ui(ctx)

    @command(name="resume", description="resumes music")
    async def resume_(self, ctx):
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            embed = discord.Embed(
                title="",
                description="I'm not connected to a voice channel",
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)
        elif not vc.is_paused():
            return

        vc.resume()
        embed = discord.Embed(
            title="Resuming ▶",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)
        await self.update_ui(ctx)

    @command(
        name="skip", description="skips to next song in queue"
    )
    async def skip_(self, ctx):
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            raise DiscordException("I'm not connected to a voice channel")

        if vc.is_paused():
            pass
        elif not vc.is_playing():
            return

        embed = discord.Embed(
            title="Skipping",
            description="Let's play something else",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)

        vc.stop()
        await self.update_ui(ctx)

    @command(
        name="remove", description="removes specified song from queue",
    )
    async def remove_(self, ctx, pos: int = None):
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            raise DiscordException("I'm not connected to a voice channel")

        player = self.get_player(ctx)
        if pos == None:
            player.queue._queue.pop()
        else:
            try:
                s = player.queue._queue[pos - 1]
                del player.queue._queue[pos - 1]
                embed = discord.Embed(
                    title="",
                    description=f"Removed [{s['title']}]({s['webpage_url']}) [{s['requester'].mention}]",
                    color=discord.Color.green(),
                )
                await ctx.send(embed=embed)
            except:
                raise DiscordException(f'Could not find a track for "{pos}"')
        await self.update_ui(ctx)

    @command(
        name="clear", description="clears entire queue"
    )
    async def clear_(self, ctx):
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            raise DiscordException("I'm not connected to a voice channel")

        player = self.get_player(ctx)
        player.queue._queue.clear()
        embed = discord.Embed(
            title="Cleared",
            description=f"Queue cleared ♻️",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)
        await self.update_ui(ctx)

    @command(
        name="queue", description="shows the queue"
    )
    async def queue_(self, ctx):
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            raise DiscordException("I'm not connected to a voice channel")

        player = self.get_player(ctx)
        if player.queue.empty():
            embed = discord.Embed(
                title="", description="queue is empty", color=discord.Color.green()
            )
            return await ctx.send(embed=embed)

        upcoming = list(
            itertools.islice(player.queue._queue, 0, int(len(player.queue._queue)))
        )
        fmt = "\n".join(
            f"`{(upcoming.index(_)) + 1}.` [{_['title']}]({_['webpage_url']}) | `Requested by: {_['requester']}`\n"
            for _ in upcoming
        )
        fmt = (
            f"\n__Now Playing__:\n[{vc.source.title}]({vc.source.web_url}) | ` {get_duration(ctx)} Requested by: {vc.source.requester}`\n\n__Up Next:__\n"
            + fmt
            + f"\n**{len(upcoming)} songs in queue**"
        )
        embed = discord.Embed(
            title=f"Queue for {ctx.guild.name}",
            description=fmt,
            color=discord.Color.green(),
        )

        await ctx.send(embed=embed)

    @command(
        name="leave", description="Stops music and disconnects from voice",
    )
    async def leave_(self, ctx):
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            raise DiscordException("I'm not connected to a voice channel")

        embed = discord.Embed(
            title="Disconnected",
            description=f"Successfully disconnected 👋",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)

        await self.cleanup(ctx.guild)
        await self.update_ui(ctx)

    @command(
        name="ui", description="Open UI for voice module",
    )
    async def ui(self, ctx):
        ui = UI(ctx, self)
        await ui.init()
        self.uis[ctx.guild.id] = ui
