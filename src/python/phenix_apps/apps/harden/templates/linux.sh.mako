#!/bin/bash
# phenix harden: ${hostname}. Runs once at boot, then deletes itself.
set -u
trap 'rm -f -- "$0"' EXIT
result=/etc/phenix/harden.result

fail() { echo "harden: $*" | tee "$result" >&2; exit 1; }

% for name, password in users.items():
chpasswd <<'PHENIX_HARDEN' || fail "set the password of ${name}"
${name}:${password}
PHENIX_HARDEN
echo "set password: ${name}"
% endfor

% for name in remove_users:
if id -u ${name} > /dev/null 2>&1; then
    pkill -KILL -u ${name} > /dev/null 2>&1 || true
    userdel -r -f ${name} > /dev/null 2>&1 || fail "remove ${name}"
    echo "removed user: ${name}"
else
    echo "no such user, nothing to remove: ${name}"
fi
% endfor

% if ssh.root_login != "unchanged" or ssh.empty_passwords == "no":
# set_sshd <directive> <value>: sshd keeps the first value it reads, so put the
# directive on line 1 and drop its other lines
set_sshd() {
    sed -i -E -e "1i $1 $2" -e "/^[#[:space:]]*$1([[:space:]]|$)/Id" /etc/ssh/sshd_config
}

if [ -f /etc/ssh/sshd_config ]; then
% if ssh.root_login != "unchanged":
    set_sshd PermitRootLogin ${ssh.root_login} || fail "edit the sshd configuration"
% endif
% if ssh.empty_passwords == "no":
    set_sshd PermitEmptyPasswords no || fail "edit the sshd configuration"
% endif
    # sshd -t needs this directory, which only exists once the ssh unit has started
    mkdir -p /run/sshd
    sshd -t || fail "sshd rejected the edited configuration"
    # The startup runner is not ordered after sshd: reload it if it is up,
    # otherwise it reads the new configuration when it starts.
    systemctl try-reload-or-restart ssh 2> /dev/null ||
        systemctl try-reload-or-restart sshd 2> /dev/null ||
        fail "reload sshd"
    echo "sshd configured"
else
    echo "no /etc/ssh/sshd_config, sshd settings skipped"
fi
% endif

% if ssh.empty_passwords == "no":
for pam in /etc/pam.d/common-auth /etc/pam.d/system-auth /etc/pam.d/password-auth; do
    if [ -f "$pam" ] && grep -Eq '\bnullok(_secure)?\b' "$pam"; then
        sed -i --follow-symlinks -E 's/[[:space:]]+nullok(_secure)?\b//g' "$pam" || fail "edit $pam"
        echo "removed nullok: $pam"
    fi
done
% endif

echo ok > "$result"
