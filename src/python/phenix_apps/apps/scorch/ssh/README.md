# SSH Component

Scorch component to execute commands on a remote host and copy files from a remote host.

```
type:   ssh
exe:    phenix-scorch-component-ssh
stages: configure, start, stop, cleanup
```

## Metadata Options

```yaml
metadata:
  ip: <string> # (REQUIRED) Login IP of the Remote Collection Server. 
  user: <string> # (REQUIRED) User name of the Remote Collection Server. 
  password: <string> # (OPTIONAL) Password of the Remote Collection Server. If not provided, the connection will be attempted without a password, meaning and SSH key will need to be already established with the remote server and available at the default location ($HOME/.ssh). If running phenix in a container, the SSH key will need to be in /root/.ssh in the container.
  cmds: 
    - <string> # (REQUIRED) Command to execute on the Remote Collection Server.
    - <string> # (OPTIONAL) Additional Commands to execute on the Remote Collection Server.
  files:
    - <string> # (OPTIONAL) Remote file or directory to pull using SFTP. Files will be saved in the scorch artifacts directory under stage name.
```

## Example Configuration

```yaml
components:
  - name: ssh-example
    type: ssh
    metadata:
      ip: 192.168.1.4
      user: ubuntu
      password: ubuntu
      cmds:
        - echo "hello from $(cat /etc/hostname)"
          
```