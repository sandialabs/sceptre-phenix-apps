package util

import "slices"

func StringSliceContains(haystack []string, needles ...string) bool {
	for _, val := range haystack {
		if slices.Contains(needles, val) {
			return true
		}
	}

	return false
}
