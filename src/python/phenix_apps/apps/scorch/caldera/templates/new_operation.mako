<%! import json %>
key=$(cat /opt/caldera/conf/default.yml | grep api_key_red | cut -d' ' -f2)

curl -X POST -H 'Content-Type: application/json' -H 'Accept: application/json' -H "KEY: $key" http://localhost:8888/api/v2/operations -d '{
  "name": ${json.dumps(op['name'])},
  "auto_close": true,
  "adversary": {
    "adversary_id": ${json.dumps(op['adversary'])}
  },
  "planner": {
    "id": ${json.dumps(op['planner'])}
  },
  "source": {
    "id": ${json.dumps(op['facts'])}
  }
}'
