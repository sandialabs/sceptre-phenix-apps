<% num_tags = 0 %>
<% scada_tags = [] %>
% for channel in opc_config.channel_list:
	% for device in channel.devices:
		% for tag in device.tags:
			<% num_tags = num_tags + 1 %>
			<% scada_tag = f"{channel.name}.Device{device.fd_name.title()}.{tag.devname}_{tag.regtype}_{tag.field}".replace("-", "_") %>
			<% scada_tags.append(scada_tag) %>
		%endfor
	%endfor
%endfor
<% height = num_tags*20 + 66 %>
<svg contentScriptType="text/ecmascript" zoomAndPan="magnify" xmlns:xlink="http://www.w3.org/1999/xlink" contentStyleType="text/css" version="1.1" width="1280" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" preserveAspectRatio="xMidYMid meet" xmlns:myscada="http://www.myscada.org" viewBox="0 0 1280.0 ${height}.0" inkscape:voditka="{&quot;voditkoHorValues&quot;:[],&quot;voditkoVerValues&quot;:[]}" height="${height}" xmlns="http://www.w3.org/2000/svg">
<style id="mySCADAFontCSSs" xml:space="preserve">
</style>
<defs/>
<rect x="0" width="1280" id="pozadiNoSeL" height="${height}" y="0" style="fill:#ffffff;stoke:#ffffff;"/>
<style type="text/css" xml:space="preserve">
* {    -webkit-touch-callout: none;    -webkit-user-select: none; /* Disable selection/Copy of UIWebView */}</style>
<g inkscape:layerlabel="Background" inkscape:groupmode="layer" id="layer0">
% for i in range(num_tags):
	<% y_pos = i*20 + 66 %>
<text x="168" y="${y_pos}" id="text${i}" style="fill:#000000;stroke:none; font-family:&apos;Tahoma&apos;; font-size:12pt; font-style:normal; font-weight:normal;" inkscape:label="{&quot;align&quot;:&quot;Right&quot;,&quot;attr&quot;:&quot;get&quot;,&quot;tag&quot;:&quot;2:\&quot;${scada_tags[i]}\&quot;@OPC&quot;,&quot;alias&quot;:&quot;2:\&quot;${scada_tags[i]}\&quot;&quot;,&quot;plcName&quot;:&quot;&quot;,&quot;type&quot;:&quot;Value&quot;,&quot;param&quot;:&quot;Decimal&quot;,&quot;stringType&quot;:&quot;10;0;Automatic&quot;}">
${scada_tags[i]} ##.#</text>
%endfor
</g>
<g inkscape:groupmode="layer" myscada:layerActiveArea="YES" id="layer1" inkscape:layerlabel="ActiveArea"/>
</svg>
