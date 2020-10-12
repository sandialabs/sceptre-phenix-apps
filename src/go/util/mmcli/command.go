// Taken (almost) as-is from minimega/miniweb.

package mmcli

import (
	"fmt"
	"strings"
)

type CommandOption func(*Command)

func Columns(c ...string) CommandOption {
	return func(cmd *Command) {
		cmd.Columns = append(cmd.Columns, c...)
	}
}

func Filters(f ...string) CommandOption {
	return func(cmd *Command) {
		cmd.Filters = append(cmd.Filters, f...)
	}
}

func Namespace(n string) CommandOption {
	return func(cmd *Command) {
		cmd.Namespace = n
	}
}

// Command represents a command and options to send to minimega.
type Command struct {
	Command   string
	Columns   []string
	Filters   []string
	Namespace string
}

// NewCommand returns a pointer to a new, initialized command.
func NewCommand(opts ...CommandOption) *Command {
	cmd := new(Command)

	cmd.Options(opts...)

	return cmd
}

func (this *Command) Options(opts ...CommandOption) {
	for _, opt := range opts {
		opt(this)
	}
}

// String builds the actual command string to send to minimega using the command
// fields.
func (c *Command) String() string {
	cmd := c.Command

	// Apply filters first so we don't need to worry about the columns not
	// including the filtered fields.
	for _, f := range c.Filters {
		cmd = fmt.Sprintf(".filter %v %v", f, cmd)
	}

	if len(c.Columns) > 0 {
		columns := make([]string, len(c.Columns))

		// Quote all the columns in case there are spaces.
		for i := range c.Columns {
			columns[i] = fmt.Sprintf("%q", c.Columns[i])
		}

		cmd = fmt.Sprintf(".columns %v %v", strings.Join(columns, ","), cmd)
	}

	// If there's a namespace, use it.
	if c.Namespace != "" {
		cmd = fmt.Sprintf("namespace %q %v", c.Namespace, cmd)
	}

	// Don't record command in history.
	cmd = fmt.Sprintf(".record false %v", cmd)

	return cmd
}
