<%namespace name="opc_channel" file="opc_channel_template.mako"/>\
<?xml version="1.0" encoding="utf-8"?>
<servermain:Project xmlns:servermain="http://www.kepware.com/schemas/servermain">
	<servermain:ServerVersion>5.18.673.0</servermain:ServerVersion>
	<servermain:Title/>
	<servermain:Comments/>
	<servermain:AliasList/>
	<servermain:ChannelList>
	% for channel in opc_config.channel_list:
${opc_channel.create(channel)}\
	% endfor
	</servermain:ChannelList>
	<servermain:PlugInList>
		<servermain:PlugIn>
			<servermain:FriendlyName>Connection Sharing Plug-in</servermain:FriendlyName>
			<servermain:CustomPlugInProperties/>
		</servermain:PlugIn>
	</servermain:PlugInList>
</servermain:Project>
