key=$(cat /opt/caldera/conf/default.yml | grep api_key_red | cut -d' ' -f2)

curl -X GET -H 'Accept: application/json' -H "KEY: $key" http://localhost:8888/api/v2/${model}