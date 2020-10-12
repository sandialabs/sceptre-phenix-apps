package util

import (
	"os"
	"strings"
)

var HostnameSuffixes = []string{"-minimega", "-phenix"}

func TrimHostnameSuffixes(str string) string {
	for _, s := range HostnameSuffixes {
		str = strings.TrimSuffix(str, s)
	}

	return str
}

func IsHeadnode(node string) bool {
	hostname, _ := os.Hostname()

	// Trim node name suffixes (like -minimega, or -phenix) potentially added to
	// Docker containers by Docker Compose config.
	hostname = TrimHostnameSuffixes(hostname)
	node = TrimHostnameSuffixes(node)

	return node == hostname
}
