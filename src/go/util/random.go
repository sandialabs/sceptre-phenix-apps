// https://stackoverflow.com/a/22892986

package util

import (
	"math/rand"
)

var chars = []rune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

func RandomString(n int) string {
	var (
		buf = make([]rune, n)
		l   = len(chars)
	)

	for i := range buf {
		//nolint:gosec // simple random string, not cryptographically relevant
		buf[i] = chars[rand.Intn(l)]
	}

	return string(buf)
}
