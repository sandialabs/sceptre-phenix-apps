<%
# Define the register type mappings
REG_TAG = {}
REG_TAG['analog-input']     = {'datatype': 'Float',   'access': 'Read Only'}
REG_TAG['analog-output']    = {'datatype': 'Float',   'access': 'Read/Write'}
REG_TAG['binary-input']     = {'datatype': 'Boolean', 'access': 'Read Only'}
REG_TAG['binary-output']    = {'datatype': 'Boolean', 'access': 'Read/Write'}
REG_TAG['input-register']   = {'datatype': 'Word',    'access': 'Read Only'}
REG_TAG['holding-register'] = {'datatype': 'Word',    'access': 'Read/Write'}
REG_TAG['discrete-input']   = {'datatype': 'Boolean', 'access': 'Read Only'}
REG_TAG['coil']             = {'datatype': 'Boolean', 'access': 'Read/Write'}
REG_TAG['float-point']      = {'datatype': 'Float',   'access': 'Read Only'}
REG_TAG['single-point']     = {'datatype': 'Boolean', 'access': 'Read Only'}

# Helper function to determine analog/digital
def get_signal_type(regtype):
    datatype = REG_TAG[regtype]['datatype']
    return 'analog' if datatype in ['Float', 'Word'] else 'digital'

# Helper function to determine input/output
def get_direction(regtype):
    access = REG_TAG[regtype]['access']
    return 'input' if access == 'Read Only' else 'output'
%>

<% num_tags = 0 %>
<% scada_tags = [] %>
<% tag_list = [] %>
% for channel in opc_config.channel_list:
    % for device in channel.devices:
        % for tag in device.tags:
            <% num_tags = num_tags + 1 %>
            <% scada_tag = f"{channel.name}.Device{device.fd_name.title()}.{tag.devname}_{tag.regtype}_{tag.field}".replace("-", "_") %>
            <% scada_tags.append(scada_tag) %>
            <% tag_list.append(tag) %>
        % endfor
    % endfor
% endfor
<% height = num_tags*50 + 130 %>

<svg contentScriptType="text/ecmascript"
     zoomAndPan="magnify"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     contentStyleType="text/css"
     version="1.1"
     width="1280"
     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     preserveAspectRatio="xMidYMid meet"
     xmlns:myscada="http://www.myscada.org"
     viewBox="0 0 1280.0 ${height}.0"
     inkscape:voditka="{&quot;voditkoHorValues&quot;:[],&quot;voditkoVerValues&quot;:[]}"
     height="${height}"
     xmlns="http://www.w3.org/2000/svg">
  <style id="mySCADAFontCSSs" xml:space="preserve">
  </style>
  <defs/>
  <rect x="0"
        width="1280"
        id="pozadiNoSeL"
        height="${height}"
        y="0"
        style="fill:#ffffff;stroke:#ffffff;"/>
  <style type="text/css" xml:space="preserve">
    * {
        -webkit-touch-callout: none;
        -webkit-user-select: none; /* Disable selection/Copy of UIWebView */
    }
  </style>
  <g inkscape:layerlabel="Background"
     inkscape:groupmode="layer"
     id="layer0">
    % for i in range(num_tags):
        <% y_pos = i*50 + 100 %>
        % if get_direction(tag_list[i].regtype) == 'input':
            <text x="250"
                  y="${y_pos + 20}"
                  id="text${i}"
                  style="fill:#000000;stroke:none;font-family:'Tahoma';font-size:12pt;"
                  inkscape:label="{&quot;align&quot;:&quot;Right&quot;,&quot;attr&quot;:&quot;get&quot;,&quot;tag&quot;:&quot;2:\&quot;${scada_tags[i]}\&quot;@OPC&quot;,&quot;alias&quot;:&quot;2:\&quot;${scada_tags[i]}\&quot;&quot;,&quot;plcName&quot;:&quot;&quot;,&quot;type&quot;:&quot;Value&quot;,&quot;param&quot;:&quot;Decimal&quot;,&quot;stringType&quot;:&quot;10;0;Automatic&quot;}"> ##.#</text>
            <text x="300"
                  y="${y_pos + 20}"
                  style="fill:#000000;font-family:'Tahoma';font-size:12pt;">
                ${scada_tags[i]}
            </text>
        % else:
            % if get_signal_type(tag_list[i].regtype) == 'analog':
                <g id="CompGenericSet${i}"
                   inkscape:componentSize="178.57143;630.0;0.0;0.0"
                   inkscape:componentData="{&quot;attr&quot;:&quot;Comp&quot;,&quot;name&quot;:&quot;Display&quot;,&quot;desc&quot;:&quot;Digital display&quot;,&quot;author&quot;:&quot;mySCADA Team&quot;,&quot;uniqueID&quot;:&quot;generic-set-${i}&quot;,&quot;MasterID&quot;:&quot;000000001&quot;,&quot;list&quot;:[{&quot;variableName&quot;:&quot;color1&quot;,&quot;name&quot;:&quot;Base color&quot;,&quot;desc&quot;:&quot;Set color&quot;,&quot;value&quot;:&quot;#0099CC&quot;,&quot;type&quot;:4},{&quot;variableName&quot;:&quot;color3&quot;,&quot;name&quot;:&quot;Stroke color&quot;,&quot;desc&quot;:&quot;Set color&quot;,&quot;value&quot;:&quot;#0099CC&quot;,&quot;type&quot;:4},{&quot;variableName&quot;:&quot;txt&quot;,&quot;name&quot;:&quot;Text&quot;,&quot;desc&quot;:&quot;Edit text&quot;,&quot;value&quot;:&quot;Set&quot;,&quot;type&quot;:1},{&quot;variableName&quot;:&quot;size&quot;,&quot;name&quot;:&quot;Text size&quot;,&quot;desc&quot;:&quot;Set size&quot;,&quot;value&quot;:&quot;12&quot;,&quot;type&quot;:2},{&quot;variableName&quot;:&quot;color2&quot;,&quot;name&quot;:&quot;Text color&quot;,&quot;desc&quot;:&quot;Set color&quot;,&quot;value&quot;:&quot;#FFFFFF&quot;,&quot;type&quot;:4},{&quot;variableName&quot;:&quot;glow&quot;,&quot;name&quot;:&quot;Glow&quot;,&quot;desc&quot;:&quot;Set glow&quot;,&quot;value&quot;:&quot;0&quot;,&quot;type&quot;:5}]}"
                   inkscape:label="{&quot;attr&quot;:&quot;setlist&quot;,&quot;listClick&quot;:[{&quot;attr&quot;:&quot;set&quot;,&quot;tag&quot;:&quot;2:${scada_tags[i]}@OPC&quot;,&quot;alias&quot;:&quot;2:${scada_tags[i]}&quot;,&quot;plcName&quot;:&quot;&quot;,&quot;prompt&quot;:&quot;&quot;,&quot;src&quot;:&quot;&quot;,&quot;type&quot;:&quot;&quot;,&quot;memory&quot;:&quot;NO&quot;,&quot;logging&quot;:&quot;NO&quot;,&quot;loggingText&quot;:&quot;&quot;,&quot;stringType&quot;:&quot;10;0;Automatic&quot;,&quot;lockEnable&quot;:&quot;NO&quot;,&quot;title&quot;:&quot;Enter a value for the tag – no limits are enforced.&quot;,&quot;batchID&quot;:1,&quot;data&quot;:{&quot;mainType&quot;:&quot;tag&quot;,&quot;setType&quot;:&quot;numeric&quot;,&quot;valueMin&quot;:&quot;&quot;,&quot;valueMax&quot;:&quot;&quot;,&quot;valueDec&quot;:&quot;2&quot;,&quot;valueType&quot;:&quot;dec&quot;,&quot;isPassword&quot;:false,&quot;connection&quot;:&quot;OPC&quot;}}],&quot;listDown&quot;:[],&quot;listUp&quot;:[]}">
                    <linearGradient id="genericSetGlow${i}"
                                    gradientUnits="userSpaceOnUse"
                                    x1="0"
                                    y1="0"
                                    x2="0"
                                    y2="1">
                        <stop offset="0%" style="stop-color:#333333;stop-opacity:0.19;"/>
                        <stop offset="100%" style="stop-color:#ffffff;stop-opacity:0.31;"/>
                    </linearGradient>
                    <rect x="100"
                          y="${y_pos}"
                          width="80"
                          height="30"
                          rx="10"
                          ry="10"
                          style="fill:#0099CC;stroke:#0099CC;stroke-width:2;"
                          inkscape:vypln="color1,100"
                          inkscape:vyplnStroke="color3"/>
                    <rect x="100"
                          y="${y_pos}"
                          width="80"
                          height="30"
                          rx="10"
                          ry="10"
                          style="visibility:hidden;fill:url(#genericSetGlow${i});stroke:none;"
                          inkscape:opac="glow;1;1"/>
                    <text x="100"
                          y="${y_pos}"
                          transform="matrix(1 0 0 1 40 21)"
                          style="font-weight:bold;text-anchor:middle;font-size:12pt;font-family:'Ubuntu';fill:#FFFFFF;stroke:none;"
                          id="genericSetLabel${i}"
                          inkscape:textFontSize="size">
                        Set
                    </text>
                    <path d="M0 0L10 0L10 10L0 10L0 0Z"
                          id="genericSetPositionCheck${i}"
                          style="display:none"
                          transform="matrix(1 0 0 1 99 99)"/>
                </g>
                <text x="250"
                      y="${y_pos + 20}"
                      id="text${i}"
                      style="fill:#000000;stroke:none;font-family:'Tahoma';font-size:12pt;"
                      inkscape:label="{&quot;align&quot;:&quot;Right&quot;,&quot;attr&quot;:&quot;get&quot;,&quot;tag&quot;:&quot;2:\&quot;${scada_tags[i]}\&quot;@OPC&quot;,&quot;alias&quot;:&quot;2:\&quot;${scada_tags[i]}\&quot;&quot;,&quot;plcName&quot;:&quot;&quot;,&quot;type&quot;:&quot;Value&quot;,&quot;param&quot;:&quot;Decimal&quot;,&quot;stringType&quot;:&quot;10;0;Automatic&quot;}"> </text>
                <text x="300"
                      y="${y_pos + 20}"
                      style="fill:#000000;font-family:'Tahoma';font-size:12pt;">
                    ${scada_tags[i]}
                </text>
            % else:
                <g id="CompGenericSet1"
                   inkscape:componentSize="178.57143;630.0;0.0;0.0"
                   inkscape:componentData="{&quot;attr&quot;:&quot;Comp&quot;,&quot;name&quot;:&quot;Display&quot;,&quot;desc&quot;:&quot;Digital display&quot;,&quot;author&quot;:&quot;mySCADA Team&quot;,&quot;uniqueID&quot;:&quot;generic-set-1&quot;,&quot;MasterID&quot;:&quot;000000001&quot;,&quot;list&quot;:[{&quot;variableName&quot;:&quot;color1&quot;,&quot;name&quot;:&quot;Base color&quot;,&quot;desc&quot;:&quot;Set color&quot;,&quot;value&quot;:&quot;#0099CC&quot;,&quot;type&quot;:4},{&quot;variableName&quot;:&quot;color3&quot;,&quot;name&quot;:&quot;Stroke color&quot;,&quot;desc&quot;:&quot;Set color&quot;,&quot;value&quot;:&quot;#0099CC&quot;,&quot;type&quot;:4},{&quot;variableName&quot;:&quot;txt&quot;,&quot;name&quot;:&quot;Text&quot;,&quot;desc&quot;:&quot;Edit text&quot;,&quot;value&quot;:&quot;Set&quot;,&quot;type&quot;:1},{&quot;variableName&quot;:&quot;size&quot;,&quot;name&quot;:&quot;Text size&quot;,&quot;desc&quot;:&quot;Set size&quot;,&quot;value&quot;:&quot;12&quot;,&quot;type&quot;:2},{&quot;variableName&quot;:&quot;color2&quot;,&quot;name&quot;:&quot;Text color&quot;,&quot;desc&quot;:&quot;Set color&quot;,&quot;value&quot;:&quot;#FFFFFF&quot;,&quot;type&quot;:4},{&quot;variableName&quot;:&quot;glow&quot;,&quot;name&quot;:&quot;Glow&quot;,&quot;desc&quot;:&quot;Set glow&quot;,&quot;value&quot;:&quot;0&quot;,&quot;type&quot;:5}]}"
                   inkscape:label="{&quot;attr&quot;:&quot;setlist&quot;,&quot;listClick&quot;:[{&quot;attr&quot;:&quot;set&quot;,&quot;tag&quot;:&quot;2:${scada_tags[1]}@OPC&quot;,&quot;alias&quot;:&quot;2:${scada_tags[1]}&quot;,&quot;plcName&quot;:&quot;&quot;,&quot;prompt&quot;:&quot;&quot;,&quot;src&quot;:&quot;toggle&quot;,&quot;type&quot;:&quot;&quot;,&quot;memory&quot;:&quot;NO&quot;,&quot;logging&quot;:&quot;NO&quot;,&quot;loggingText&quot;:&quot;&quot;,&quot;stringType&quot;:&quot;10.0;Automatic&quot;,&quot;LockEnable&quot;:&quot;NO&quot;,&quot;title&quot;:&quot;Set the binary value (0 / 1).&quot;,&quot;batchID&quot;:1}] ,&quot;listDown&quot;:[],&quot;listUp&quot;:[]}">
                    <linearGradient id="genericSetGlow1"
                                    gradientUnits="userSpaceOnUse"
                                    x1="0"
                                    y1="0"
                                    x2="0"
                                    y2="1">
                        <stop offset="0%" style="stop-color:#333333;stop-opacity:0.19;"/>
                        <stop offset="100%" style="stop-color:#ffffff;stop-opacity:0.31;"/>
                    </linearGradient>
                    <rect x="100"
                          y="${y_pos}"
                          width="80"
                          height="30"
                          rx="10"
                          ry="10"
                          style="fill:#D32F2F;stroke:#D32F2F;stroke-width:2;"
                          inkscape:opac="display;0.0;inline"/>
                    <rect x="100"
                          y="${y_pos}"
                          width="80"
                          height="30"
                          rx="10"
                          ry="10"
                          style="fill:#388E3C;stroke:#388E3C;stroke-width:2;"
                          inkscape:opac="display;1.0;inline"/>
                    <text x="100"
                          y="${y_pos}"
                          transform="matrix(1 0 0 1 40 21)"
                          style="font-weight:bold;
                                 text-anchor:middle;
                                 font-size:12pt;
                                 font-family:'Ubuntu';
                                 fill:#FFFFFF;
                                 stroke:none;"
                          id="genericSetLabel1"
                          inkscape:textFontSize="size">
                        <tspan inkscape:label="{&quot;attr&quot;:&quot;get&quot;,&quot;tag&quot;:&quot;2:${scada_tags[1]}@OPC&quot;,&quot;alias&quot;:&quot;2:${scada_tags[1]}&quot;,&quot;type&quot;:&quot;Value&quot;,&quot;param&quot;:&quot;Decimal&quot;,&quot;stringType&quot;:&quot;10;0;Automatic&quot;}">
                            Toggle
                        </tspan>
                    </text>
                    <path d="M0 0L10 0L10 10L0 10Z"
                          id="genericSetPositionCheck1"
                          style="display:none"
                          transform="matrix(1 0 0 1 99 99)"/>
                </g>
                <text x="250"
                      y="${y_pos + 20}"
                      id="text${i}"
                      style="fill:#000000;stroke:none;font-family:'Tahoma';font-size:12pt;"
                      inkscape:label="{&quot;align&quot;:&quot;Right&quot;,&quot;attr&quot;:&quot;get&quot;,&quot;tag&quot;:&quot;2:\&quot;${scada_tags[i]}\&quot;@OPC&quot;,&quot;alias&quot;:&quot;2:\&quot;${scada_tags[i]}\&quot;&quot;,&quot;plcName&quot;:&quot;&quot;,&quot;type&quot;:&quot;Value&quot;,&quot;param&quot;:&quot;Decimal&quot;,&quot;stringType&quot;:&quot;10;0;Automatic&quot;}"></text>
                <text x="300"
                      y="${y_pos + 20}"
                      style="fill:#000000;font-family:'Tahoma';font-size:12pt;">
                    ${scada_tags[i]}
                </text>
            % endif
        % endif
    % endfor
  </g>

  <g inkscape:groupmode="layer"
     myscada:layerActiveArea="YES"
     id="layer1"
     inkscape:layerlabel="ActiveArea"/>
</svg>
