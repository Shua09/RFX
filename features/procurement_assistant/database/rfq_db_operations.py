# src/features/procurement_assistant/database/rfq_db_operations.py
from datetime import datetime
import json
from typing import Dict, Any, List, Optional
from ....common.db_pyodbc import get_db_connection
from ....common.logging_config import get_logger

logger = get_logger(__name__)

class RFQDatabaseOperations:
    def __init__(self):
        self.connection = None
        self.cursor = None
        
    def __enter__(self):
        self.connection = get_db_connection()
        self.cursor = self.connection.cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
    
    def _format_date_for_sql(self, date_value: Optional[str]) -> Optional[str]:
        """
        Format date properly for SQL Server
        SQL Server expects YYYY-MM-DD format
        """
        if not date_value:
            return None
        
        try:
            # If it's already a datetime object
            if isinstance(date_value, datetime):
                return date_value.strftime('%Y-%m-%d')
            
            # If it's a string, try to parse common formats
            if isinstance(date_value, str):
                # Remove any time portion if present
                date_value = date_value.split(' ')[0].split('T')[0]
                
                # Try different date formats
                for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y']:
                    try:
                        parsed_date = datetime.strptime(date_value, fmt)
                        # Return in SQL Server format
                        return parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                        continue
            
            return None
        except Exception as e:
            logger.warning(f"Date formatting failed for {date_value}: {str(e)}")
            return None
    
    def _safe_str(self, value: Any) -> Optional[str]:
        """Convert value to string safely, handling None"""
        if value is None:
            return None
        return str(value)
    
    def generate_rfq_id(self) -> str:
        today = datetime.now().strftime('%Y%m%d')
        
        self.cursor.execute("""
            SELECT COUNT(*) FROM [RFQ].[rfq_headers]
            WHERE rfq_id LIKE ?
        """, (f'RFQ-{today}-%',))
        
        count = self.cursor.fetchone()[0] + 1
        return f"RFQ-{today}-{count:04d}"
    
    def create_rfq(
        self,
        session_id: str,
        rfq_data: Dict[str, Any],
        user_id: Optional[str] = None,
        department: Optional[str] = None,
        required_date: Optional[str] = None,
        delivery_deadline: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new RFQ from confirmed conversation data
        
        Args:
            session_id: Conversation session ID
            rfq_data: The JSON data from conversation (items, budget, etc.)
            user_id: Optional user ID if logged in
            department: Optional department name
            required_date: Optional required date (YYYY-MM-DD)
            delivery_deadline: Optional delivery deadline (YYYY-MM-DD)
        
        Returns:
            Dict with status and RFQ ID
        """
        
        try:
            rfq_id = self.generate_rfq_id()
            
            total_budget = rfq_data.get('budget_total', 0)
            currency = rfq_data.get('currency', 'USD')
            items = rfq_data.get('items', [])
            
            # Format dates properly for SQL Server
            formatted_required_date = self._format_date_for_sql(required_date)
            formatted_delivery_deadline = self._format_date_for_sql(delivery_deadline)
            
            # Also check if dates are in rfq_data
            if not formatted_required_date and rfq_data.get('required_date'):
                formatted_required_date = self._format_date_for_sql(rfq_data.get('required_date'))
            
            if not formatted_delivery_deadline and rfq_data.get('delivery_deadline'):
                formatted_delivery_deadline = self._format_date_for_sql(rfq_data.get('delivery_deadline'))
            
            logger.info(f"Creating RFQ {rfq_id} with dates: required={formatted_required_date}, deadline={formatted_delivery_deadline}")
            
            # Insert header
            self.cursor.execute("""
                INSERT INTO [RFQ].[rfq_headers]
                (rfq_id, session_id, user_id, department, status,
                total_budget, currency, required_date, delivery_deadline,
                created_at, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), GETDATE())
            """,(
                rfq_id,
                self._safe_str(session_id),
                self._safe_str(user_id),
                self._safe_str(department),
                'CONFIRMED',
                total_budget,
                currency,
                formatted_required_date,
                formatted_delivery_deadline,
            ))
            
            # Insert line items
            for idx, item in enumerate(items, 1):
                quantity = item.get('quantity', 0)
                unit_price = item.get('unit_price', 0)
                total_price = quantity * unit_price if unit_price else 0
                
                specifications = json.dumps(item.get('specifications', {}), ensure_ascii=False)
                
                self.cursor.execute("""
                    INSERT INTO [RFQ].[rfq_line_items]
                    (rfq_id, line_number, category, brand, model, 
                     part_number, description, specifications, quantity,
                     unit_price, total_price, currency, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
                """, (
                    rfq_id,
                    idx,
                    item.get('category', 'Unknown'),
                    item.get('brand'),
                    item.get('model'),
                    item.get('part_number'),
                    item.get('description'),
                    specifications,
                    quantity,
                    unit_price,
                    total_price,
                    item.get('currency', currency)
                ))
            
            # Commit the transaction
            self.connection.commit()
            
            logger.info(f"RFQ {rfq_id} created successfully for session {session_id}")
            
            return {
                "status": "success",
                "rfq_id": rfq_id,
                "message": f"RFQ {rfq_id} created successfully"
            }
            
        except Exception as e:
            # Rollback on error
            self.connection.rollback()
            logger.error(f"Error creating RFQ: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to create RFQ: {str(e)}"
            }
    
    def get_rfq_by_id(self, rfq_id: str) -> Dict[str, Any]:
        """Get RFQ details by ID"""
        try:
            # Get header
            self.cursor.execute("""
                SELECT rfq_id, session_id, user_id, department, status,
                       total_budget, currency, 
                       FORMAT(required_date, 'yyyy-MM-dd') as required_date,
                       FORMAT(delivery_deadline, 'yyyy-MM-dd') as delivery_deadline,
                       FORMAT(created_at, 'yyyy-MM-dd HH:mm:ss') as created_at,
                       FORMAT(updated_at, 'yyyy-MM-dd HH:mm:ss') as updated_at,
                       FORMAT(confirmed_at, 'yyyy-MM-dd HH:mm:ss') as confirmed_at
                FROM [RFQ].[rfq_headers]
                WHERE rfq_id = ?
            """, (rfq_id,))
            
            header = self.cursor.fetchone()
            if not header:
                return {
                    "status": "error",
                    "message": f"RFQ {rfq_id} not found"
                }
            
            # Get line items
            self.cursor.execute("""
                SELECT line_number, category, brand, model, part_number,
                       description, specifications, quantity, unit_price,
                       total_price, currency,
                       FORMAT(created_at, 'yyyy-MM-dd HH:mm:ss') as created_at
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (rfq_id,))
            
            items = []
            for row in self.cursor.fetchall():
                items.append({
                    "line_number": row[0],
                    "category": row[1],
                    "brand": row[2],
                    "model": row[3],
                    "part_number": row[4],
                    "description": row[5],
                    "specifications": json.loads(row[6]) if row[6] else {},
                    "quantity": row[7],
                    "unit_price": float(row[8]) if row[8] else 0,
                    "total_price": float(row[9]) if row[9] else 0,
                    "currency": row[10],
                    "created_at": row[11]
                })
            
            return {
                "status": "success",
                "rfq": {
                    "rfq_id": header[0],
                    "session_id": header[1],
                    "user_id": header[2],
                    "department": header[3],
                    "status": header[4],
                    "total_budget": float(header[5]),
                    "currency": header[6],
                    "required_date": header[7],
                    "delivery_deadline": header[8],
                    "created_at": header[9],
                    "updated_at": header[10],
                    "confirmed_at": header[11],
                    "items": items,
                    "item_count": len(items),
                    "total_quantity": sum(item['quantity'] for item in items)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting RFQ {rfq_id}: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def get_rfqs_by_session(self, session_id: str) -> Dict[str, Any]:
        """Get all RFQs for a session"""
        try:
            self.cursor.execute("""
                SELECT rfq_id, status, total_budget, currency,
                       FORMAT(created_at, 'yyyy-MM-dd HH:mm:ss') as created_at,
                       FORMAT(confirmed_at, 'yyyy-MM-dd HH:mm:ss') as confirmed_at,
                       (SELECT COUNT(*) FROM [RFQ].[rfq_line_items] WHERE rfq_id = h.rfq_id) as item_count
                FROM [RFQ].[rfq_headers] h
                WHERE session_id = ?
                ORDER BY created_at DESC
            """, (session_id,))
            
            rfqs = []
            for row in self.cursor.fetchall():
                rfqs.append({
                    "rfq_id": row[0],
                    "status": row[1],
                    "total_budget": float(row[2]),
                    "currency": row[3],
                    "created_at": row[4],
                    "confirmed_at": row[5],
                    "item_count": row[6]
                })
            
            return {
                "status": "success",
                "session_id": session_id,
                "rfqs": rfqs,
                "total_count": len(rfqs)
            }
            
        except Exception as e:
            logger.error(f"Error getting RFQs for session {session_id}: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def update_rfq_status(self, rfq_id: str, status: str) -> Dict[str, Any]:
        """Update RFQ status"""
        valid_statuses = ['DRAFT', 'CONFIRMED', 'PROCESSING', 'COMPLETED', 'CANCELLED']
        
        if status not in valid_statuses:
            return {
                "status": "error",
                "message": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            }
        
        try:
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_headers]
                SET status = ?
                WHERE rfq_id = ?
            """, (status, rfq_id))
            
            self.connection.commit()
            
            if self.cursor.rowcount > 0:
                logger.info(f"RFQ {rfq_id} status updated to {status}")
                return {
                    "status": "success",
                    "message": f"RFQ {rfq_id} status updated to {status}"
                }
            else:
                return {
                    "status": "error",
                    "message": f"RFQ {rfq_id} not found"
                }
                
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error updating RFQ {rfq_id} status: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def delete_rfq(self, rfq_id: str) -> Dict[str, Any]:
        """Delete an RFQ (soft delete by changing status to CANCELLED)"""
        return self.update_rfq_status(rfq_id, 'CANCELLED')
    
    def test_connection(self) -> Dict[str, Any]:
        """Test database connection and basic operations"""
        try:
            # Test 1: Simple query
            self.cursor.execute("SELECT 1 as test")
            result = self.cursor.fetchone()
            
            # Test 2: Check if tables exist
            self.cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'RFQ' AND TABLE_NAME = 'rfq_headers'
            """)
            headers_exists = self.cursor.fetchone()[0] > 0
            
            self.cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'RFQ' AND TABLE_NAME = 'rfq_line_items'
            """)
            items_exists = self.cursor.fetchone()[0] > 0
            
            return {
                "status": "success",
                "connection": "OK",
                "headers_table": headers_exists,
                "items_table": items_exists,
                "message": "Database connection successful"
            }
        except Exception as e:
            logger.error(f"Database connection test failed: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }