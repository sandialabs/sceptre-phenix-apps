package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"path"
	"strings"

	"phenix-apps/tmpl"
	"phenix-apps/util"
	"phenix/types"

	"github.com/mitchellh/mapstructure"
)

const InjectDir = "/minimega"

type Metadata struct {
	AgentDir string `mapstructure:"agentDir"`
}

type HostMetadata struct {
	Agent         string `mapstructure:"agent"`
	AgentArgs     string `mapstructure:"agentArgs"`
	AutoStart     bool   `mapstructure:"autoStart"`
	CustomService struct {
		ScriptPath string `mapstructure:"scriptPath"`
		InjectPath string `mapstructure:"injectPath"`
	} `mapstructure:"serviceCustom"`
	ServiceType string `mapstructure:"serviceType"`
}

func main() {
	if len(os.Args) != 2 {
		log.Fatal("incorrect amount of args provided")
	}

	body, err := ioutil.ReadAll(os.Stdin)
	if err != nil {
		log.Fatal("unable to read JSON from STDIN")
	}

	stage := os.Args[1]

	if stage != "configure" && stage != "pre-start" {
		fmt.Print(string(body))
		return
	}

	exp, err := util.DecodeExperiment(body)
	if err != nil {
		log.Fatalf("decoding experiment: %v", err)
	}

	switch stage {
	case "configure":
		if err := configure(exp); err != nil {
			log.Fatalf("failed to execute configure stage: %v", err)
		}
	case "pre-start":
		if err := preStart(exp); err != nil {
			log.Fatalf("failed to execute pre-start stage: %v", err)
		}
	}

	body, err = json.Marshal(exp)
	if err != nil {
		log.Fatal("unable to convert experiment to JSON")
	}

	fmt.Print(string(body))
}

func configure(exp *types.Experiment) error {
	startupDir := exp.Spec.BaseDir() + "/startup"

	app := util.ExtractApp(exp.Spec.Scenario(), "cc-dropper")

	if app == nil {
		// TODO: yell loudly
		return nil
	}

	var md Metadata

	if err := mapstructure.Decode(app.Metadata(), &md); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	for _, host := range app.Hosts() {
		var hmd HostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			// TODO: yell loudly
			continue
		}

		node := util.FindNodeByNameRegex(exp, host.Hostname())

		if node == nil {
			// TODO: yell loudly
			continue
		}

		agentPath := md.AgentDir + "/" + hmd.Agent

		switch strings.ToUpper(node.Hardware().OSType()) {
		case "WINDOWS":
			var (
				startupFile = startupDir + "/" + node.General().Hostname() + "-cc-startup.ps1"
				schedFile   = startupDir + "/" + node.General().Hostname() + "-cc-scheduler.cmd"
			)

			if !strings.HasSuffix(agentPath, ".exe") {
				agentPath = agentPath + ".exe"
			}

			node.AddInject(startupFile, InjectDir+"/cc-startup.ps1", "", "")
			node.AddInject(schedFile, "ProgramData/Microsoft/Windows/Start Menu/Programs/StartUp/CommandAndControl.cmd", "", "")
			node.AddInject(agentPath, InjectDir+path.Base(agentPath), "", "")
		default:
			var (
				startupFile = startupDir + "/" + node.General().Hostname() + "-cc-startup.sh"
				svcFile     = startupDir + "/" + node.General().Hostname() + "-cc-startup.service"
				svcLink     = startupDir + "/symlinks/cc-startup.service"
			)

			switch strings.ToLower(hmd.ServiceType) {
			case "systemd":
				node.AddInject(startupFile, InjectDir+"/cc-startup.sh", "", "")
				node.AddInject(svcFile, "/etc/systemd/system/CommandAndControl.service", "", "")
				node.AddInject(svcLink, "/lib/systemd/system/multi-user.target.wants/CommandAndControl.service", "", "")
			case "custom":
				node.AddInject(startupFile, hmd.CustomService.InjectPath, "", "")
			default:
				node.AddInject(startupFile, InjectDir+"/cc-startup.sh", "", "")
				node.AddInject(svcFile, "/etc/init.d/CommandAndControl", "", "")
				node.AddInject(svcLink, "/etc/rc5.d/S99CommandAndControl", "", "")
			}

			node.AddInject(agentPath, InjectDir+path.Base(agentPath), "", "")
		}
	}

	return nil
}

func preStart(exp *types.Experiment) error {
	startupDir := exp.Spec.BaseDir() + "/startup"

	app := util.ExtractApp(exp.Spec.Scenario(), "cc-dropper")

	if app == nil {
		// TODO: yell loudly
		return nil
	}

	var md Metadata

	if err := mapstructure.Decode(app.Metadata(), &md); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	for _, host := range app.Hosts() {
		var hmd HostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			// TODO: yell loudly
			continue
		}

		node := util.FindNodeByNameRegex(exp, host.Hostname())

		if node == nil {
			// TODO: yell loudly
			continue
		}

		switch strings.ToUpper(node.Hardware().OSType()) {
		case "WINDOWS":
			startupFile := startupDir + "/" + node.General().Hostname() + "-cc-startup.ps1"

			if err := tmpl.CreateFileFromTemplate("cc-dropper/windows-startup.tmpl", hmd, startupFile, 0755); err != nil {
				return fmt.Errorf("generating windows command and control startup script: %w", err)
			}

			startupFile = startupDir + "/" + node.General().Hostname() + "-cc-scheduler.cmd"

			if err := tmpl.CreateFileFromTemplate("cc-dropper/windows-scheduler.tmpl", hmd, startupFile, 0755); err != nil {
				return fmt.Errorf("generating windows command and control service script: %w", err)
			}
		default:
			startupFile := startupDir + "/" + node.General().Hostname() + "-cc-startup.sh"

			if err := tmpl.CreateFileFromTemplate("cc-dropper/linux-startup.tmpl", hmd, startupFile, 0755); err != nil {
				return fmt.Errorf("generating linux command and control startup script: %w", err)
			}

			switch strings.ToLower(hmd.ServiceType) {
			case "systemd":
				startupFile = startupDir + "/" + node.General().Hostname() + "-cc-startup.service"

				if err := tmpl.CreateFileFromTemplate("cc-dropper/systemd-service.tmpl", hmd, startupFile, 0644); err != nil {
					return fmt.Errorf("generating linux command and control service script: %w", err)
				}

				startupFile = startupDir + "/symlinks/cc-startup.service"

				if err := os.Symlink("../CommandAndControl.service", startupFile); err != nil {
					// Ignore the error if it was for the symlinked file already existing.
					if !strings.Contains(err.Error(), "file exists") {
						return fmt.Errorf("generating linux command and control service link: %w", err)
					}
				}
			case "custom":
				if hmd.CustomService.ScriptPath != "" {
					if _, err := os.Stat(hmd.CustomService.ScriptPath); err != nil {
						return fmt.Errorf("custom service script not found on disk")
					}

					body, err := ioutil.ReadFile(hmd.CustomService.ScriptPath)
					if err != nil {
						return fmt.Errorf("reading custom service script %s: %w", hmd.CustomService.ScriptPath, err)
					}

					custom := strings.Split(string(body), "\n")
					custom = append(custom, "##### Gernerated by phenix cc-dropper app ######")

					//Generate the template into a string
					existing := new(bytes.Buffer)

					if err := tmpl.GenerateFromTemplate("cc-dropper/linux-startup.tmpl", hmd, existing); err != nil {
						return fmt.Errorf("generating linux command and control startup script: %w", err)
					}

					//Grab all the startup stuff for CC and add it the the users script
					custom = append(custom, strings.Split(existing.String(), "\n")...)

					err = ioutil.WriteFile(startupFile, []byte(strings.Join(custom, "\n")), 0755)
					if err != nil {
						return fmt.Errorf("writing %s: %w", startupFile, err)
					}
				}
			default:
				startupFile = startupDir + "/" + node.General().Hostname() + "-cc-startup.service"

				if err := tmpl.CreateFileFromTemplate("cc-dropper/sysinitv-service.tmpl", hmd, startupFile, 0755); err != nil {
					log.Fatal("generating linux command and control service script: ", err)
				}

				startupFile = startupDir + "/symlinks/cc-startup.service"

				if err := os.Symlink("../CommandAndControl", startupFile); err != nil {
					// Ignore the error if it was for the symlinked file already existing.
					if !strings.Contains(err.Error(), "file exists") {
						return fmt.Errorf("generating linux command and control service link: %w", err)
					}
				}
			}
		}
	}

	return nil
}
