package main

import (
	"example.com/sample-001/services/internal/launch"
	"log"
)

func main() {
	if err := launch.Worker("scan"); err != nil {
		log.Fatal(err)
	}
}
