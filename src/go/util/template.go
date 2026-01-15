package util

import (
	"embed"
	"fmt"
	"io"
	"io/ioutil"
	"os"
	"path/filepath"
	"text/template"
)

func GenerateFromTemplate(name string, tmpl []byte, data any, w io.Writer) error {
	t := template.Must(template.New(name).Parse(string(tmpl)))

	err := t.Execute(w, data)
	if err != nil {
		return fmt.Errorf("executing %s template: %w", name, err)
	}

	return nil
}

func CreateFileFromTemplate(name string, tmpl []byte, data any, filename string) error {
	dir := filepath.Dir(filename)

	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("creating template path: %w", err)
	}

	//nolint:gosec //G304 creating file
	f, err := os.OpenFile(filename, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return fmt.Errorf("creating template file: %w", err)
	}

	defer f.Close()

	return GenerateFromTemplate(name, tmpl, data, f)
}

func RestoreAsset(templates embed.FS, path, name string) error {
	data, err := templates.ReadFile(name)
	if err != nil {
		return fmt.Errorf("reading asset %q: %w", name, err)
	}

	file, err := templates.Open(name)
	if err != nil {
		return fmt.Errorf("opening asset %q: %w", name, err)
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		return fmt.Errorf("statting asset %q: %w", name, err)
	}

	err = os.MkdirAll(filepath.Dir(path), os.FileMode(0o755))
	if err != nil {
		return fmt.Errorf("creating directory for %q: %w", path, err)
	}

	err = ioutil.WriteFile(path, data, info.Mode())
	if err != nil {
		return fmt.Errorf("writing file %q: %w", path, err)
	}

	err = os.Chtimes(path, info.ModTime(), info.ModTime())
	if err != nil {
		return fmt.Errorf("setting times for %q: %w", path, err)
	}

	return nil
}
