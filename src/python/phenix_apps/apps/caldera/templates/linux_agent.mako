server="http://${addr}:8888"

until curl --output /dev/null --silent --fail $server ; do
  echo "Problem starting Sandcat agent... retrying in 5s"
  sleep 5
done

agent=$(curl -svkOJ -X POST -H "file:sandcat.go" -H "platform:linux" $server/file/download 2>&1 | grep -i "Content-Disposition" | grep -io "filename=.*" | cut -d'=' -f2 | tr -d '"\r') && chmod +x $agent 2>/dev/null

nohup ./$agent -server $server &

echo "Sandcat agent started"
