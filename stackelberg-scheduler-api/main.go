package main

import (
	"context"
	"fmt"
	"os"

	"k8s.io/component-base/logs"
	"k8s.io/kubernetes/cmd/kube-scheduler/app"

	"stackelberg-scheduler-api/pkg/plugins/stackelberg"
)

func main() {
	command := app.NewSchedulerCommand(
		app.WithPlugin(stackelberg.Name, stackelberg.New),
	)

	logs.InitLogs()
	defer logs.FlushLogs()

	ctx := context.Background()
	if err := command.ExecuteContext(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}
}