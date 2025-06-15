from django.core.management.base import BaseCommand
from crontab import CronTab
import os
import sys


class Command(BaseCommand):
    help = 'Setup cron job for automatic J&J WCS discovery'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=str,
            default='daily',
            choices=['hourly', 'daily', 'weekly'],
            help='How often to run the discovery'
        )
        
        parser.add_argument(
            '--remove',
            action='store_true',
            help='Remove the cron job'
        )
    
    def handle(self, *args, **options):
        # Get current user's crontab
        cron = CronTab(user=True)
        
        # Define job command
        python_path = sys.executable
        manage_path = os.path.abspath('manage.py')
        job_command = f'{python_path} {manage_path} auto_discover --days-back 7 --max-videos 20'
        job_comment = 'J&J WCS Auto Discovery'
        
        if options['remove']:
            # Remove existing jobs
            removed = 0
            for job in cron.find_comment(job_comment):
                cron.remove(job)
                removed += 1
            
            if removed:
                cron.write()
                self.stdout.write(self.style.SUCCESS(f'Removed {removed} cron job(s)'))
            else:
                self.stdout.write(self.style.WARNING('No cron jobs found to remove'))
            return
        
        # Remove existing jobs first
        for job in cron.find_comment(job_comment):
            cron.remove(job)
        
        # Create new job
        job = cron.new(command=job_command, comment=job_comment)
        
        # Set schedule based on interval
        if options['interval'] == 'hourly':
            job.minute.on(0)
            schedule_desc = 'every hour'
        elif options['interval'] == 'daily':
            job.hour.on(2)  # Run at 2 AM
            job.minute.on(0)
            schedule_desc = 'daily at 2:00 AM'
        elif options['interval'] == 'weekly':
            job.dow.on(0)  # Sunday
            job.hour.on(2)  # 2 AM
            job.minute.on(0)
            schedule_desc = 'weekly on Sunday at 2:00 AM'
        
        # Write the cron job
        cron.write()
        
        self.stdout.write(self.style.SUCCESS(f'Cron job created to run {schedule_desc}'))
        self.stdout.write(f'Command: {job_command}')
        
        # Show all jobs for this project
        self.stdout.write('\nAll J&J WCS cron jobs:')
        for job in cron.find_comment(job_comment):
            self.stdout.write(f'  {job}')