package util

import (
	"os"
	"strings"

	log "github.com/activeshadow/libminimega/minilog"
)

func SetupLogging() {
	var (
		output = os.Stderr
		level  = log.DefaultLevel
	)

	if fname := os.Getenv("PHENIX_LOG_FILE"); fname != "" {
		var err error

		output, err = os.OpenFile(os.Getenv("PHENIX_LOG_FILE"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			log.AddLogger("stderr", os.Stderr, log.DEBUG, false)
			log.Fatal("cannot open PHENIX_LOG_FILE (%s) for writing", os.Getenv("PHENIX_LOG_FILE"))
		}
	}

	if lname := os.Getenv("PHENIX_LOG_LEVEL"); lname != "" {
		var err error

		level, err = log.ParseLevel(strings.ToLower(os.Getenv("PHENIX_LOG_LEVEL")))
		if err != nil {
			log.AddLogger("stderr", os.Stderr, log.DEBUG, false)
			log.Fatal("unable to parse PHENIX_LOG_LEVEL (%s)", os.Getenv("PHENIX_LOG_LEVEL"))
		}
	}

	log.AddLogger("default", output, level, false)
}
