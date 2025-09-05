# Church Books - Church Management System

Church Books is a comprehensive church management system built with Django that helps churches manage their members, finances, contributions, and transactions.

## Features

### 1. User Management & Authentication
- **Church Registration**: New churches can register and await admin approval
- **Role-Based Access Control**: Different roles with specific permissions
  - Pastor
  - Assistant Pastor
  - Church Admin
  - Treasurer
  - Deacon

### 2. Member Management
- Add, edit, and view church members
- Track member details:
  - Personal information
  - Contact details
  - Baptism date
  - Membership status
  - Emergency contacts

### 3. Financial Management

#### Contributions
- Record and track member contributions
- Multiple contribution types:
  - Tithes
  - Offerings
  - Special Offerings
  - Building Fund
  - Missions
- Support various payment methods:
  - Cash
  - Check
  - Credit/Debit Card
  - Bank Transfer
  - Mobile Money

#### Transactions
- Record church income and expenses
- Categorized transactions:
  - Income Categories:
    - Tithes
    - Offerings
    - Donations
    - Fundraising
  - Expense Categories:
    - Salaries
    - Utilities
    - Rent/Mortgage
    - Missions
    - Benevolence
    - Supplies
    - Maintenance
    - Events

### 4. Reporting
- Monthly contribution reports
- Yearly contribution reports
- Monthly transaction reports
- Yearly transaction reports
- Financial dashboard with:
  - Total income
  - Total expenses
  - Net balance
  - Recent transactions

## Technical Requirements

- Python 3.12+
- Django 5.2+
- Database: SQLite (default)

## Installation

1. Clone the repository:
\`\`\`bash
git clone https://github.com/grant8827/gcem_webapp.git
cd gcem-dbs
\`\`\`

2. Create a virtual environment:
\`\`\`bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
\`\`\`

3. Install dependencies:
\`\`\`bash
pip install -r requirements.txt
\`\`\`

4. Apply migrations:
\`\`\`bash
python manage.py migrate
\`\`\`

5. Create a superuser:
\`\`\`bash
python manage.py createsuperuser
\`\`\`

6. Run the development server:
\`\`\`bash
python manage.py runserver
\`\`\`

## Usage Guide

### Initial Setup

1. **Church Registration**
   - Register your church through the registration page
   - Wait for admin approval
   - Once approved, you can start using the system

2. **Adding Staff Members**
   - Pastors and admins can add new staff members
   - Staff members added through the dashboard are automatically approved
   - Assign appropriate roles to staff members

### Daily Operations

1. **Managing Members**
   - Add new members with their details
   - Update member information as needed
   - Track member status (active/inactive)

2. **Recording Contributions**
   - Record member contributions
   - Specify contribution type and payment method
   - Generate contribution receipts

3. **Managing Transactions**
   - Record church income and expenses
   - Categorize transactions appropriately
   - Monitor church finances through the dashboard

4. **Generating Reports**
   - Generate monthly/yearly contribution reports
   - Generate monthly/yearly transaction reports
   - View financial summaries on the dashboard

## Security Features

- Role-based access control
- Password protection for all accounts
- Church approval system
- Secure financial record keeping
- Data validation and sanitization
- CSRF protection

## Application Structure

```
church_finance_project/
│
├── church_finances/          # Main application
│   ├── migrations/          # Database migrations
│   ├── templates/          # HTML templates
│   ├── admin.py           # Admin interface configuration
│   ├── forms.py           # Form definitions
│   ├── models.py          # Database models
│   ├── urls.py            # URL routing
│   └── views.py           # View logic
│
├── static/                 # Static files (CSS, JS, images)
├── templates/             # Base templates
├── manage.py              # Django management script
└── requirements.txt       # Project dependencies
```

## Best Practices

1. **Financial Records**
   - Always verify transaction details before saving
   - Regularly generate and review financial reports
   - Keep backup copies of important financial data

2. **Member Management**
   - Update member information regularly
   - Maintain accurate contact details
   - Document any status changes

3. **System Administration**
   - Regularly backup the database
   - Monitor user permissions and roles
   - Keep the system updated

## Support

For issues or feature requests, please:
1. Check the existing documentation
2. Contact system administrator
3. Submit an issue on GitHub

## License

Copyright © 2024 Church Books. All rights reserved.
