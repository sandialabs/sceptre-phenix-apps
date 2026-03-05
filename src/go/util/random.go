// https://stackoverflow.com/a/22892986

package util

import (
	"math/rand/v2"
)

const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

func RandomString(n int) string {
	var (
		buf = make([]byte, n)
		l   = len(chars)
	)

	for i := range buf {
		//nolint:gosec // simple random string, not cryptographically relevant
		buf[i] = chars[rand.IntN(l)]
	}

	return string(buf)
}
