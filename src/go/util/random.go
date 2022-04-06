// https://stackoverflow.com/a/22892986

package util

import (
	"math/rand"
	"time"
)

var chars = []rune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

func init() {
	rand.Seed(time.Now().UnixNano())
}

func RandomString(n int) string {
	var (
		buf = make([]rune, n)
		len = len(chars)
	)

	for i := range buf {
		buf[i] = chars[rand.Intn(len)]
	}

	return string(buf)
}
