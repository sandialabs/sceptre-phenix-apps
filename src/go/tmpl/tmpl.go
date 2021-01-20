package tmpl

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"text/template"
)

func GenerateFromTemplate(name string, data interface{}, w io.Writer) error {
	t := template.Must(template.New(name).Parse(string(MustAsset(name))))

	if err := t.Execute(w, data); err != nil {
		return fmt.Errorf("executing %s template: %w", name, err)
	}

	return nil
}

func CreateFileFromTemplate(name string, data interface{}, filename string, perm os.FileMode) error {
	dir := filepath.Dir(filename)

	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("creating template path: %w", err)
	}

	f, err := os.OpenFile(filename, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, perm)
	if err != nil {
		return fmt.Errorf("creating template file: %w", err)
	}

	defer f.Close()

	return GenerateFromTemplate(name, tmpl, data, f)
}
