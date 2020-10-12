package util

func StringSliceContains(haystack []string, needles ...string) bool {
	for _, val := range haystack {
		for _, needle := range needles {
			if val == needle {
				return true
			}
		}
	}

	return false
}
