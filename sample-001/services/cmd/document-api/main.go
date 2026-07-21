package main

import (
	"example.com/sample-001/services/internal/launch"
	"log"
)

func main() {
	if err := launch.API(); err != nil {
		log.Fatal(err)
	}
}
