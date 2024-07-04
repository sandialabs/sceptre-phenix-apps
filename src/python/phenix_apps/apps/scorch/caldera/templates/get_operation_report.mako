key=$(cat /opt/caldera/conf/default.yml | grep api_key_red | cut -d' ' -f2)

curl -X POST -H 'Content-Type: application/json' -H 'Accept: application/json' -H "KEY: $key" http://localhost:8888/api/v2/operations/${op}/report -d '{
  "enable_agent_output": true
}'

