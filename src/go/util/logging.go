package util

import (
	"fmt"
	"log/slog"
	"os"
	"strings"
	"time"
)

func SetupLogging() {
	var (
		output = os.Stderr
		level  = slog.LevelInfo
	)

	if fname := os.Getenv("PHENIX_LOG_FILE"); fname == "stderr" {
		output = os.Stderr
	} else if fname != "" {
		f, err := os.OpenFile(
			fname,
			os.O_APPEND|os.O_CREATE|os.O_WRONLY,
			0o644,
		)
		if err == nil {
			output = f
		} else {
			fmt.Fprintf(os.Stderr, "cannot open PHENIX_LOG_FILE for writing file=%s\n", fname)
		}
	}

	if lname := os.Getenv("PHENIX_LOG_LEVEL"); lname != "" {
		err := level.UnmarshalText([]byte(strings.ToUpper(os.Getenv("PHENIX_LOG_LEVEL"))))
		if err != nil {
			fmt.Fprintf(
				os.Stderr,
				"unable to parse PHENIX_LOG_LEVEL. Expected one of: DEBUG, INFO, WARN, ERROR level=%s\n",
				os.Getenv("PHENIX_LOG_LEVEL"),
			)
		}
	}

	handlerOpts := &slog.HandlerOptions{
		Level:     level,
		AddSource: true,
		ReplaceAttr: func(_ []string, a slog.Attr) slog.Attr {
			if a.Key == slog.TimeKey {
				if t, ok := a.Value.Any().(time.Time); ok {
					a.Value = slog.StringValue(t.Format("2006-01-02 15:04:05.000"))
				}
			}

			return a
		},
	}

	var logger *slog.Logger
	if os.Getenv("PHENIX_LOG_FILE") == "stderr" || os.Getenv("PHENIX_LOG_FILE") != "" {
		logger = slog.New(slog.NewJSONHandler(output, handlerOpts))
	} else {
		logger = slog.New(slog.NewTextHandler(output, handlerOpts))
	}

	slog.SetDefault(logger)
}
