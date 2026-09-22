
from beets.ui import Subcommand
from beets import plugins
from beets.plugins import BeetsPlugin

PLUGIN_BLACKLIST = ["jar"]

class WebPluginCommand:

    def __init__(self, command: Subcommand):
        self.command = command.name
        self.command_options = []

        for option in command.parser._get_all_options():
            if option.dest is None:
                # e.g. -h/--help has no dest and no value of its own
                continue

            self.command_options.append({
                "name": option.dest,
                "flags": option._short_opts + option._long_opts,
                "type": self._infer_type(option),
                "default": command.parser.defaults.get(option.dest, option.default),
                "help": option.help,
            })
        print(self.command)
        for command_option in self.command_options:
            for key, value in command_option.items():
                print(f"{key}: {value}")

    @staticmethod
    def _infer_type(option):
        # store_true/store_false/count/append actions don't set `option.type`,
        # so the action itself is what tells us the real value type
        if option.action in ("store_true", "store_false"):
            return "bool"
        if option.action == "count":
            return "int"
        if option.action == "append":
            return "list"
        return option.type or "string"



class WebPlugin:
    def __init__(self, plugin: BeetsPlugin):
        self.plugin = plugin
        self.command_list = self.build_command_list()

    def build_command_list(self):

        command_list = []
        for command in self.plugin.commands():
            command_list.append(WebPluginCommand(command))

        return command_list



def get_loaded_plugins():

    web_plugins = {}

    for plugin in plugins.find_plugins():
        if plugin.name in PLUGIN_BLACKLIST:
            continue
        web_plugins[plugin.name] = WebPlugin(plugin)




