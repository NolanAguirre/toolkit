package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(stop)

	// Read WRITE_DIR, DATABASE_URL or DB_FILE with os.Getenv when needed.
	log.Print("service started")
	<-stop
	log.Print("service stopped")
}
