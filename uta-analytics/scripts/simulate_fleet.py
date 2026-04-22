#!/usr/bin/env python3
import os
import sys
import time
import shutil
import argparse
import threading
from pathlib import Path

def simulate_board(source_path: Path, output_dir: Path, filename: str, delay: float, batch_size: int):
    output_path = output_dir / filename
    completed_dir = output_dir / "completed"
    completed_dir.mkdir(parents=True, exist_ok=True)
    completed_path = completed_dir / filename

    print(f"[Thread] Starting simulation for {filename}")
    
    # Clear existing file
    with open(output_path, 'w') as f_out:
        pass
        
    lines_written = 0
    try:
        with open(source_path, 'r') as f_in, open(output_path, 'a') as f_out:
            lines_batch = []
            
            for line in f_in:
                lines_batch.append(line)
                
                if len(lines_batch) >= batch_size:
                    for l in lines_batch:
                        f_out.write(l)
                    f_out.flush()
                    lines_written += len(lines_batch)
                    lines_batch = []
                    time.sleep(delay)
                    
            if lines_batch:
                for l in lines_batch:
                    f_out.write(l)
                f_out.flush()
                lines_written += len(lines_batch)
                
        print(f"[Thread] Finished streaming {filename} ({lines_written} lines). Moving to 'completed' folder...")
        # Simulate moving the file to trigger the test_completed event!
        shutil.move(str(output_path), str(completed_path))
        print(f"[Thread] {filename} successfully moved. Test Completed.")
        
    except Exception as e:
        print(f"[Thread Error] {filename}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Simulate multiple boards running concurrently.")
    parser.add_argument("input_file", help="Path to the base source log file")
    parser.add_argument("--output-dir", default="./vector/logs", help="Directory where Vector is listening")
    parser.add_argument("--boards", type=int, default=3, help="Number of concurrent boards to simulate")
    parser.add_argument("--delay", type=float, default=0.01, help="Delay in seconds between batches")
    parser.add_argument("--batch-size", type=int, default=10, help="Lines to write at once")
    
    args = parser.parse_args()
    source_path = Path(args.input_file)
    
    if not source_path.exists():
        print(f"Error: {source_path} does not exist.")
        sys.exit(1)
        
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    base_name = source_path.name
    
    threads = []
    # Try to find a slot identifier to replace, e.g., R7S3-09
    # If the filename has "R7S3-09", we can replace the "09" part
    prefix = "R7S3-"
    
    print(f"Launching {args.boards} simultaneous board simulations...")
    
    for i in range(1, args.boards + 1):
        # Create a unique filename for each simulated board
        slot_str = f"{i:02d}"  # 01, 02, 03...
        
        if prefix in base_name:
            # Replace the slot number in the filename
            parts = base_name.split(prefix)
            end_parts = parts[1].split("_", 1)
            new_filename = f"{parts[0]}{prefix}{slot_str}_{end_parts[1]}"
        else:
            # Fallback if filename doesn't contain R7S3-
            new_filename = f"SIM-SLOT{slot_str}_{base_name}"
            
        t = threading.Thread(
            target=simulate_board, 
            args=(source_path, output_dir, new_filename, args.delay, args.batch_size)
        )
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    print("\nAll simulations completed! Check Grafana to see the dashboards and test sessions.")

if __name__ == "__main__":
    main()
