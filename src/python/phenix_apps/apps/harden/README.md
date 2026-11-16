# Harden App

Harden experiments that are booted from default-open (i.e. passwordless `root:` images). Uses an inject script that runs after phenix startup script to set passwords, remove users, and configure ssh or autologon. Once done, the inject script writes a status file `harden.result` for post-checks, and then deletes itself. Expected results (including what passwords will be set to in-experiment) is recorded in the experiment directory, `harden/credentials.yml`. Every booting `VirtualMachine` with `os_type:` `linux`, `rhel`, `centos` or `windows` is targeted. Routers, `external` and `do_not_boot` nodes are skipped.

* **Linux:** set account passwords, remove accounts, set ssh options
* **Windows:** set local account passwords, remove local accounts, keep or disable autologon.

```
name:   harden
exe:    phenix-app-harden
stages: pre-start
```

## Metadata

#### App level:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `seed` | string, 8-256 characters | | Secret generated passwords derive from. Required when any user has `generate: true` |
| `exclude` | list of hostnames | `[]` | VMs to leave alone |
| `linux` | block, below | | What to do on every Linux VM |
| `windows` | block, below | | What to do on every Windows VM |

#### `linux` and `windows` blocks:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `users` | map of account name to `{password: ...}` or `{generate: true}` | `{}` | Passwords to set. A literal `password` is 8-127 printable characters; on Windows it also needs three of upper case, lower case, digits and symbols, and must not contain the account name. `generate: true` derives one from `seed` |
| `remove_users` | list of account names | `[]` | Accounts to delete: `userdel -r` on Linux, the account and its profile on Windows. `root` and `Administrator` are refused |
| `ssh.root_login` | `unchanged`, `prohibit-password` or `no` | `unchanged` | Linux only: sshd `PermitRootLogin` |
| `ssh.empty_passwords` | `unchanged` or `no` | `unchanged` | Linux only: `no` sets `PermitEmptyPasswords no` and drops PAM `nullok`, so an account with no password cannot log in |
| `autologon` | `keep` or `disable` | `keep` | Windows only. `keep` updates the stored autologon password when its account's password changes, so whatever starts at logon (miniccc) survives a reboot. `disable` turns autologon off: after the next reboot the VM waits at the logon screen |

#### `hosts:` blocks:
An entry under `hosts` uses the same fields as its OS block. `users` are merged by name and `ssh` field by field.

> [!NOTE]
> A domain controller (`phenix/domain-controller`) needs a host entry or an `exclude` because its local accounts are the domain's.

### Generated passwords

With `generate: true`, the password is derived from `seed`, the hostname, and the account name, so the same scenario always yields the same passwords and one can be recomputed.

```python
import hashlib, string

seed, hostname, username = "correct-horse-battery-staple", "webserv01", "root"
digest = hashlib.sha256(f"{seed}/{hostname}/{username}".encode()).digest()
classes = (string.ascii_uppercase, string.ascii_lowercase, string.digits, "!-")
alphabet = "".join(classes)
password = "".join(
    (classes[i] if i < 4 else alphabet)[b % len(classes[i] if i < 4 else alphabet)]
    for i, b in enumerate(digest[:16])
)
print(password)  # Kq2!r7UlN6nNL5KL
```

This results in a 16-character password that fulfills complexity requirements (upper, lower, digit, symbol).

## Examples

```yaml
apps:
  - name: harden
    metadata:
      seed: correct-horse-battery-staple
      exclude: [kali, AD-dc1]
      linux:
        users:
          root:
            generate: true
        ssh:
          root_login: prohibit-password
          empty_passwords: "no"
      windows:
        users:
          Administrator:
            generate: true
        remove_users: [vagrant]
```

Literal passwords, an extra local account on one engineering workstation, and
autologon switched off on a server:

```yaml
apps:
  - name: harden
    metadata:
      seed: correct-horse-battery-staple
      linux:
        users:
          root:
            password: "Tr0ub4dor&3!!"
        remove_users: [rdp]
        ssh:
          root_login: "no"
      windows:
        users:
          Administrator:
            password: "Tr0ub4dor&3!!"
    hosts:
      - hostname: webserv01
        metadata:
          users:
            nginx:
              generate: true
      - hostname: win-ftpserve
        metadata:
          autologon: disable
```

## Checking Results

#### Script Output

On each hardened VM, `/etc/phenix/harden.result` (Linux) or `C:\phenix\harden.result` (Windows) holds one of these:

| Line | Meaning and fix |
|---|---|
| `ok` | Everything went fine |
| `harden: set the password of <user>` | `chpasswd` refused; usually the account does not exist on that image |
| `harden: remove <user>` | `userdel` failed for an account that exists on that image |
| `harden: edit the sshd configuration` | `/etc/ssh/sshd_config` could not be written; sshd was not reloaded |
| `harden: sshd rejected the edited configuration` | `sshd -t` failed after the edit; sshd was not reloaded. Inspect `/etc/ssh/sshd_config` in the VM |
| `harden: reload sshd` | Neither `ssh` nor `sshd` is a systemd unit on that image |
| `harden: edit <file>` | `sed` could not rewrite that PAM file to drop `nullok` |
| `harden: no local user <user>` | The Windows account does not exist locally; domain accounts are out of scope |
| `harden: Exception calling "SetPassword" ... password does not meet the password policy requirements` | A password fails the complexity requirements |
| `harden: update the logon password of service <svc>: error N` | `Win32_Service.Change` refused the new password for a service that logs on as the account |
| `harden: cannot remove the autologon user <user> while autologon is kept` | Set `autologon: disable` on that host, or do not remove the account |

No `harden.result` at all means the script never ran.

#### SOH 

The phenix State of Health app can be used to check the results of hardening.

```yaml
apps:
  - name: soh
    metadata:
      startupDelay: 15m
      hostCustomTests:
        webserv01:
          - name: harden
            testScript: grep -qx ok /etc/phenix/harden.result && echo MACROHARDER
            testStdout: MACROHARDER
        win-ftpserve:
          - name: harden
            testScript: if ((Get-Content C:\phenix\harden.result) -eq 'ok') { 'MINIHARD' }
            testStdout: MINIHARD
```

## Limitations

- Local accounts only: on a domain-joined client the domain's accounts are untouched. Managing the domain is outside the scope of this app.
- A scheduled task that stores the password of a changed account is not updated and stops running.
- A removed Windows account that is logged on keeps its profile directory.
- Autologon is managed through the Winlogon registry values phenix's startup script writes, which Winlogon reads first.
