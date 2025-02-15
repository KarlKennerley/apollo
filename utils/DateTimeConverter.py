from discord.ext.commands import BadArgument, Converter

from utils.utils import parse_time


class DateTimeConverter(Converter):
    async def convert(self, ctx, argument):
        ret = parse_time(argument)
        if ret is None:
            raise BadArgument
        return ret
