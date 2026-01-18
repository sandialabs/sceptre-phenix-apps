package util

import (
	"os"
	"strings"

	"golang.org/x/exp/slog"
)

func SetupLogging() {
	var (
		output = os.Stderr
		level  = slog.LevelInfo
	)

	if fname := os.Getenv("PHENIX_LOG_FILE"); fname != "" {
		var err error

		output, err = os.OpenFile(
			os.Getenv("PHENIX_LOG_FILE"),
			os.O_APPEND|os.O_CREATE|os.O_WRONLY,
			0o644,
		)
		if err != nil {
			slog.Error(
				"cannot open PHENIX_LOG_FILE for writing",
				"file",
				os.Getenv("PHENIX_LOG_FILE"),
			)
		}
	}

	if lname := os.Getenv("PHENIX_LOG_LEVEL"); lname != "" {
		err := level.UnmarshalText([]byte(strings.ToUpper(os.Getenv("PHENIX_LOG_LEVEL"))))
		if err != nil {
			slog.Error(
				"unable to parse PHENIX_LOG_LEVEL. Expected one of: DEBUG, INFO, WARN, ERROR",
				"level",
				os.Getenv("PHENIX_LOG_LEVEL"),
			)
		}
	}

	logger := slog.New(slog.NewJSONHandler(output, &slog.HandlerOptions{Level: level}))

	slog.SetDefault(logger)
}
