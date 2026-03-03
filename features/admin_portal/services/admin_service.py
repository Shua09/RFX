# src/features/admin_portal/services/admin_service.py

import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from ....common.db_pyodbc import get_db_connection
from ....common.logging_config import get_logger
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from ....common.config import Config

logger = get_logger(__name__)

class AdminService:
    def __init__(self):
        self.connection = None
        self.cursor = None
        # Load email configuration from Config
        self.smtp_host = getattr(Config, 'SMTP_HOST', None)
        self.smtp_port = getattr(Config, 'SMTP_PORT', 587)
        self.smtp_user = getattr(Config, 'SMTP_EMAIL', None)
        self.smtp_pass = getattr(Config, 'SMTP_PASSWORD', None)
        self.sender_name = getattr(Config, 'SENDER_NAME', 'Procurement Department')
        self.base_url = getattr(Config, 'APP_BASE_URL', 'https://yourdomain.com')
    
    def __enter__(self):
        self.connection = get_db_connection()
        self.cursor = self.connection.cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
    
    def get_all_rfqs(self, status_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Get all RFQs with summary information for admin dashboard
        """
        try:
            query = """
                SELECT 
                    h.rfq_id,
                    h.department,
                    h.status,
                    h.total_budget,
                    h.currency,
                    h.required_date,
                    h.delivery_deadline,
                    h.created_at,
                    h.confirmed_at,
                    COUNT(DISTINCT rs.supplier_id) as total_suppliers,
                    SUM(CASE WHEN rs.quotation_received = 1 THEN 1 ELSE 0 END) as bids_received,
                    AVG(rs.match_score) as avg_match_score,
                    MIN(rs.quotation_amount) as lowest_bid,
                    MAX(rs.quotation_amount) as highest_bid,
                    (
                        SELECT COUNT(*) 
                        FROM [RFQ].[rfq_line_items] li 
                        WHERE li.rfq_id = h.rfq_id
                    ) as total_items
                FROM [RFQ].[rfq_headers] h
                LEFT JOIN [RFQ].[rfq_suppliers] rs ON h.rfq_id = rs.rfq_id
                WHERE 1=1
            """
            
            params = []
            if status_filter and status_filter != 'ALL':
                query += " AND h.status = ?"
                params.append(status_filter)
            
            query += """
                GROUP BY 
                    h.rfq_id, h.department, h.status, h.total_budget, 
                    h.currency, h.required_date, h.delivery_deadline, 
                    h.created_at, h.confirmed_at
                ORDER BY h.created_at DESC
            """
            
            self.cursor.execute(query, params)
            
            rfqs = []
            for row in self.cursor.fetchall():
                rfqs.append({
                    "rfq_id": row[0],
                    "department": row[1],
                    "status": row[2],
                    "total_budget": float(row[3]) if row[3] else 0,
                    "currency": row[4],
                    "required_date": row[5].strftime("%Y-%m-%d") if row[5] else None,
                    "delivery_deadline": row[6].strftime("%Y-%m-%d") if row[6] else None,
                    "created_at": row[7].strftime("%Y-%m-%d %H:%M") if row[7] else None,
                    "confirmed_at": row[8].strftime("%Y-%m-%d %H:%M") if row[8] else None,
                    "total_suppliers": row[9] or 0,
                    "bids_received": row[10] or 0,
                    "avg_match_score": float(row[11]) if row[11] else 0,
                    "lowest_bid": float(row[12]) if row[12] else None,
                    "highest_bid": float(row[13]) if row[13] else None,
                    "total_items": row[14] or 0,
                    "bidding_progress": f"{row[10] or 0}/{row[9] or 0}"
                })
            
            # Get status counts for filter
            self.cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM [RFQ].[rfq_headers]
                GROUP BY status
            """)
            
            status_counts = {row[0]: row[1] for row in self.cursor.fetchall()}
            
            return {
                "status": "success",
                "rfqs": rfqs,
                "filters": {
                    "status_counts": status_counts,
                    "current_filter": status_filter or "ALL"
                },
                "total_count": len(rfqs)
            }
            
        except Exception as e:
            logger.error(f"Error getting all RFQs: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_rfq_details(self, rfq_id: str) -> Dict[str, Any]:
        """
        Get detailed RFQ information including all items and supplier bids
        """
        try:
            # Get RFQ header
            self.cursor.execute("""
                SELECT 
                    rfq_id,
                    department,
                    status,
                    total_budget,
                    currency,
                    required_date,
                    delivery_deadline,
                    created_at,
                    confirmed_at,
                    session_id,
                    user_id
                FROM [RFQ].[rfq_headers]
                WHERE rfq_id = ?
            """, (rfq_id,))
            
            header_row = self.cursor.fetchone()
            if not header_row:
                return {"status": "error", "message": "RFQ not found"}
            
            # Get all line items
            self.cursor.execute("""
                SELECT 
                    line_number,
                    category,
                    brand,
                    model,
                    part_number,
                    description,
                    specifications,
                    quantity,
                    unit_price,
                    total_price,
                    currency
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (rfq_id,))
            
            items = []
            for item in self.cursor.fetchall():
                try:
                    specs = json.loads(item[6]) if item[6] else {}
                except:
                    specs = {}
                
                items.append({
                    "line_number": item[0],
                    "category": item[1] or "",
                    "brand": item[2] or "Any Brand",
                    "model": item[3] or "",
                    "part_number": item[4] or "",
                    "description": item[5] or "",
                    "specifications": specs,
                    "quantity": float(item[7]) if item[7] else 0,
                    "estimated_unit_price": float(item[8]) if item[8] else None,
                    "estimated_total_price": float(item[9]) if item[9] else None,
                    "currency": item[10] or "USD"
                })
            
            # Get all suppliers and their bids for this RFQ
            self.cursor.execute("""
                SELECT 
                    rs.mapping_id,
                    rs.supplier_id,
                    s.company_name,
                    s.contact_person,
                    s.email,
                    s.brand_representation,
                    s.product_categories,
                    rs.match_score,
                    rs.quotation_received,
                    rs.quotation_amount,
                    rs.quotation_currency,
                    rs.status as supplier_status,
                    rs.submitted_at,
                    rs.response_details,
                    rs.matching_items_json,
                    rs.partial_items_json,
                    rs.non_matching_items_json,
                    rs.non_relevant_items_json,
                    rs.last_viewed
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                WHERE rs.rfq_id = ?
                ORDER BY 
                    CASE WHEN rs.quotation_received = 1 THEN 0 ELSE 1 END,
                    rs.quotation_amount ASC
            """, (rfq_id,))
            
            suppliers = []
            for row in self.cursor.fetchall():
                # Parse JSON data
                try:
                    response_details = json.loads(row[13]) if row[13] else {}
                except:
                    response_details = {}
                
                try:
                    matching_items = json.loads(row[14]) if row[14] else []
                except:
                    matching_items = []
                
                try:
                    partial_items = json.loads(row[15]) if row[15] else []
                except:
                    partial_items = []
                
                # Get bid items if available
                bid_items = []
                if response_details and 'quotations' in response_details:
                    for quote in response_details['quotations']:
                        for product in quote.get('offered_products', []):
                            bid_items.append({
                                "line_number": quote.get('line_number'),
                                "product_name": product.get('product_name'),
                                "brand": product.get('brand'),
                                "model": product.get('model'),
                                "quantity": product.get('quantity'),
                                "unit_price": product.get('unit_price'),
                                "total_price": product.get('total_price'),
                                "delivery_date": product.get('delivery_date')
                            })
                
                supplier_data = {
                    "mapping_id": row[0],
                    "supplier_id": row[1],
                    "company_name": row[2],
                    "contact_person": row[3],
                    "email": row[4],
                    "brand_representation": row[5],
                    "product_categories": row[6],
                    "match_score": float(row[7]) if row[7] else 0,
                    "has_bid": row[8] == 1,
                    "bid_amount": float(row[9]) if row[9] else None,
                    "bid_currency": row[10] or "USD",
                    "bid_status": row[11],
                    "submitted_at": row[12].strftime("%Y-%m-%d %H:%M") if row[12] else None,
                    "last_viewed": row[18].strftime("%Y-%m-%d %H:%M") if row[18] else None,
                    "matching_items_count": len(matching_items),
                    "partial_items_count": len(partial_items),
                    "bid_details": response_details,
                    "bid_items": bid_items
                }
                
                suppliers.append(supplier_data)
            
            # Calculate statistics
            bids = [s for s in suppliers if s["has_bid"]]
            bid_amounts = [s["bid_amount"] for s in bids if s["bid_amount"]]
            
            stats = {
                "total_suppliers": len(suppliers),
                "bids_received": len(bids),
                "bids_pending": len(suppliers) - len(bids),
                "avg_bid": sum(bid_amounts) / len(bid_amounts) if bid_amounts else None,
                "lowest_bid": min(bid_amounts) if bid_amounts else None,
                "highest_bid": max(bid_amounts) if bid_amounts else None,
                "currency": header_row[4] if bid_amounts else "USD"
            }
            
            return {
                "status": "success",
                "rfq_info": {
                    "rfq_id": header_row[0],
                    "department": header_row[1],
                    "status": header_row[2],
                    "total_budget": float(header_row[3]) if header_row[3] else 0,
                    "currency": header_row[4],
                    "required_date": header_row[5].strftime("%Y-%m-%d") if header_row[5] else None,
                    "delivery_deadline": header_row[6].strftime("%Y-%m-%d") if header_row[6] else None,
                    "created_at": header_row[7].strftime("%Y-%m-%d %H:%M") if header_row[7] else None,
                    "confirmed_at": header_row[8].strftime("%Y-%m-%d %H:%M") if header_row[8] else None,
                    "session_id": header_row[9],
                    "user_id": header_row[10]
                },
                "items": items,
                "suppliers": suppliers,
                "statistics": stats,
                "total_items": len(items)
            }
            
        except Exception as e:
            logger.error(f"Error getting RFQ details: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_bid_details(self, mapping_id: int) -> Dict[str, Any]:
        """
        Get detailed bid information for a specific supplier
        """
        try:
            self.cursor.execute("""
                SELECT 
                    rs.mapping_id,
                    rs.rfq_id,
                    rs.supplier_id,
                    rs.response_details,
                    rs.quotation_amount,
                    rs.quotation_currency,
                    rs.submitted_at,
                    rs.status,
                    s.company_name,
                    s.contact_person,
                    s.email,
                    s.phone,
                    s.address,
                    s.brand_representation,
                    h.total_budget,
                    h.currency,
                    h.required_date,
                    h.delivery_deadline
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
                WHERE rs.mapping_id = ?
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Bid not found"}
            
            # Parse response details
            try:
                bid_data = json.loads(row[3]) if row[3] else {}
            except:
                bid_data = {}
            
            # Get RFQ items for comparison
            self.cursor.execute("""
                SELECT 
                    line_number,
                    category,
                    brand,
                    model,
                    part_number,
                    description,
                    quantity
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (row[1],))
            
            rfq_items = []
            for item in self.cursor.fetchall():
                rfq_items.append({
                    "line_number": item[0],
                    "category": item[1],
                    "brand": item[2],
                    "model": item[3],
                    "part_number": item[4],
                    "description": item[5],
                    "quantity": float(item[6]) if item[6] else 0
                })
            
            # Organize bid items by line number
            bid_by_line = {}
            if bid_data and 'quotations' in bid_data:
                for quote in bid_data['quotations']:
                    line_num = quote.get('line_number')
                    if line_num not in bid_by_line:
                        bid_by_line[line_num] = {
                            "original_request": quote.get('original_request', {}),
                            "offered_products": quote.get('offered_products', [])
                        }
            
            # Create comparison view
            comparison = []
            for rfq_item in rfq_items:
                line_num = rfq_item['line_number']
                if line_num in bid_by_line:
                    comparison.append({
                        "line_number": line_num,
                        "rfq_item": rfq_item,
                        "bid_response": bid_by_line[line_num],
                        "has_bid": True
                    })
                else:
                    comparison.append({
                        "line_number": line_num,
                        "rfq_item": rfq_item,
                        "bid_response": None,
                        "has_bid": False
                    })
            
            return {
                "status": "success",
                "bid_info": {
                    "mapping_id": row[0],
                    "rfq_id": row[1],
                    "supplier_id": row[2],
                    "company_name": row[8],
                    "contact_person": row[9],
                    "email": row[10],
                    "phone": row[11],
                    "address": row[12],
                    "brand_representation": row[13],
                    "bid_amount": float(row[4]) if row[4] else 0,
                    "bid_currency": row[5] or "USD",
                    "submitted_at": row[6].strftime("%Y-%m-%d %H:%M") if row[6] else None,
                    "status": row[7]
                },
                "rfq_info": {
                    "total_budget": float(row[14]) if row[14] else 0,
                    "currency": row[15],
                    "required_date": row[16].strftime("%Y-%m-%d") if row[16] else None,
                    "delivery_deadline": row[17].strftime("%Y-%m-%d") if row[17] else None
                },
                "bid_data": bid_data,
                "comparison": comparison,
                "summary": bid_data.get('summary', {}),
                "supplier_notes": bid_data.get('supplier_info', {}).get('notes', '')
            }
            
        except Exception as e:
            logger.error(f"Error getting bid details: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def update_rfq_status(self, rfq_id: str, status: str) -> Dict[str, Any]:
        """
        Update the status of an RFQ
        """
        try:
            valid_statuses = ['DRAFT', 'PUBLISHED', 'CLOSED', 'AWARDED', 'CANCELLED']
            if status not in valid_statuses:
                return {
                    "status": "error",
                    "message": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                }
            
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_headers]
                SET status = ?, updated_at = GETDATE()
                WHERE rfq_id = ?
            """, (status, rfq_id))
            
            if self.cursor.rowcount == 0:
                return {"status": "error", "message": "RFQ not found"}
            
            self.connection.commit()
            
            return {
                "status": "success",
                "message": f"RFQ status updated to {status}",
                "rfq_id": rfq_id,
                "new_status": status
            }
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error updating RFQ status: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def award_bid(self, mapping_id: int) -> Dict[str, Any]:
        """
        Award the bid to a specific supplier and send notification email
        """
        try:
            # Get RFQ ID first
            self.cursor.execute("""
                SELECT rfq_id FROM [RFQ].[rfq_suppliers]
                WHERE mapping_id = ?
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Bid not found"}
            
            rfq_id = row[0]
            
            # Update the awarded supplier
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_suppliers]
                SET status = 'AWARDED', updated_at = GETDATE()
                WHERE mapping_id = ?
            """, (mapping_id,))
            
            # Update other suppliers to LOST
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_suppliers]
                SET status = 'LOST', updated_at = GETDATE()
                WHERE rfq_id = ? AND mapping_id != ?
            """, (rfq_id, mapping_id))
            
            # Update RFQ header status to COMPLETED
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_headers]
                SET status = 'COMPLETED', updated_at = GETDATE()
                WHERE rfq_id = ?
            """, (rfq_id,))
            
            self.connection.commit()
            
            # Send award email to winning supplier
            email_sent = False
            email_error = None
            email_content = None
            
            try:
                # Generate email content
                email_content = self.generate_award_email_content(mapping_id)
                
                if email_content['status'] == 'success':
                    # Send email
                    email_sent = self.send_email(
                        to_email=email_content['to_email'],
                        subject=email_content['subject'],
                        html_body=email_content['html_body'],
                        text_body=email_content['text_body']
                    )
                    
                    if email_sent:
                        # Log email in database - FIXED: Added email_body
                        self.cursor.execute("""
                            INSERT INTO [RFQ].[email_logs]
                            (rfq_id, supplier_id, email_to, email_subject, email_body, email_type, status, created_at)
                            VALUES (?, ?, ?, ?, ?, 'AWARD', 'SENT', GETDATE())
                        """, (
                            rfq_id, 
                            self._get_supplier_id(mapping_id), 
                            email_content['to_email'], 
                            email_content['subject'],
                            email_content['text_body'],  # Store the plain text body
                        ))
                        self.connection.commit()
                        
                        logger.info(f"Award email sent to {email_content['to_email']} for mapping_id {mapping_id}")
                    else:
                        email_error = "Failed to send email"
                else:
                    email_error = email_content.get('message', 'Failed to generate email content')
                    
            except Exception as e:
                email_error = str(e)
                logger.error(f"Error sending award email: {str(e)}")
            
            # Prepare response
            response = {
                "status": "success",
                "message": "Bid awarded successfully",
                "rfq_id": rfq_id,
                "awarded_mapping_id": mapping_id,
                "email_notification": {
                    "sent": email_sent,
                    "to": email_content['to_email'] if email_content and email_sent else None
                }
            }
            
            if email_error:
                response["email_notification"]["error"] = email_error
                response["message"] += f" (Note: Award email could not be sent: {email_error})"
            else:
                response["message"] += " and notification email sent"
            
            return response
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error awarding bid: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _get_supplier_id(self, mapping_id: int) -> int:
        """Helper method to get supplier_id from mapping_id"""
        try:
            self.cursor.execute("""
                SELECT supplier_id FROM [RFQ].[rfq_suppliers]
                WHERE mapping_id = ?
            """, (mapping_id,))
            row = self.cursor.fetchone()
            return row[0] if row else None
        except:
            return None
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """
        Get dashboard statistics for admin
        """
        try:
            stats = {}
            
            # Total RFQs
            self.cursor.execute("SELECT COUNT(*) FROM [RFQ].[rfq_headers]")
            stats['total_rfqs'] = self.cursor.fetchone()[0]
            
            # RFQs by status
            self.cursor.execute("""
                SELECT status, COUNT(*) 
                FROM [RFQ].[rfq_headers]
                GROUP BY status
            """)
            stats['rfqs_by_status'] = {row[0]: row[1] for row in self.cursor.fetchall()}
            
            # Total suppliers
            self.cursor.execute("SELECT COUNT(*) FROM [RFQ].[suppliers]")
            stats['total_suppliers'] = self.cursor.fetchone()[0]
            
            # Total bids received
            self.cursor.execute("SELECT COUNT(*) FROM [RFQ].[rfq_suppliers] WHERE quotation_received = 1")
            stats['total_bids'] = self.cursor.fetchone()[0]
            
            # Average bid amount
            self.cursor.execute("SELECT AVG(quotation_amount) FROM [RFQ].[rfq_suppliers] WHERE quotation_received = 1")
            avg_bid = self.cursor.fetchone()[0]
            stats['avg_bid_amount'] = float(avg_bid) if avg_bid else 0
            
            # Recent RFQs (last 5)
            self.cursor.execute("""
                SELECT TOP 5 
                    rfq_id, 
                    department, 
                    status, 
                    created_at,
                    (SELECT COUNT(*) FROM [RFQ].[rfq_suppliers] rs WHERE rs.rfq_id = h.rfq_id) as supplier_count
                FROM [RFQ].[rfq_headers] h
                ORDER BY created_at DESC
            """)
            
            recent = []
            for row in self.cursor.fetchall():
                recent.append({
                    "rfq_id": row[0],
                    "department": row[1],
                    "status": row[2],
                    "created_at": row[3].strftime("%Y-%m-%d %H:%M") if row[3] else None,
                    "supplier_count": row[4]
                })
            
            stats['recent_rfqs'] = recent
            
            return {
                "status": "success",
                "statistics": stats
            }
            
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_rfq_with_evaluations(self, rfq_id: str) -> Dict[str, Any]:
        """Get RFQ details with AI evaluations"""
        result = self.get_rfq_details(rfq_id)
        
        if result['status'] == 'success':
            # Get evaluations for each supplier
            from .ai_bid_evaluation_service import AIBidEvaluationService
            
            with AIBidEvaluationService() as eval_service:
                comparison = eval_service.compare_bids(rfq_id)
                if comparison['status'] == 'success':
                    result['evaluations'] = comparison
        
        return result
    
    def generate_award_email_content(self, mapping_id: int) -> Dict[str, Any]:
        """Generate award notification email for winning supplier"""
        
        # Get supplier and RFQ details
        self.cursor.execute("""
            SELECT 
                rs.rfq_id,
                rs.supplier_id,
                rs.quotation_amount,
                rs.quotation_currency,
                rs.submitted_at,
                rs.response_details,
                s.company_name,
                s.contact_person,
                s.email,
                h.department,
                h.total_budget,
                h.currency,
                h.required_date,
                h.delivery_deadline,
                h.created_at
            FROM [RFQ].[rfq_suppliers] rs
            JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
            JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
            WHERE rs.mapping_id = ?
        """, (mapping_id,))
        
        data = self.cursor.fetchone()
        if not data:
            return {"status": "error", "message": "No data found"}
        
        # Parse response_details to get quoted items
        try:
            bid_data = json.loads(data[5]) if data[5] else {}
        except:
            bid_data = {}
        
        # Format dates
        award_date = datetime.now().strftime("%B %d, %Y")
        required_date = data[12].strftime("%B %d, %Y") if data[12] else "Not specified"
        delivery_deadline = data[13].strftime("%B %d, %Y") if data[13] else "Not specified"
        
        # Format amount
        try:
            amount = float(data[2]) if data[2] else 0
            formatted_amount = f"{amount:,.2f}"
        except:
            formatted_amount = "0.00"
        
        # Get other suppliers for reference
        self.cursor.execute("""
            SELECT TOP 3 
                s.company_name,
                rs.quotation_amount,
                rs.quotation_currency
            FROM [RFQ].[rfq_suppliers] rs
            JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
            WHERE rs.rfq_id = ? AND rs.mapping_id != ? AND rs.quotation_received = 1
            ORDER BY rs.quotation_amount ASC
        """, (data[0], mapping_id))
        
        other_bids = self.cursor.fetchall()
        
        # Build quoted items table
        items_html = ""
        items_text = ""
        
        quotations = bid_data.get('quotations', [])
        if quotations:
            items_html = """
            <h3>📋 Your Quoted Items</h3>
            <table style="width:100%; border-collapse: collapse; margin: 20px 0;">
                <thead>
                    <tr style="background-color: #4CAF50; color: white;">
                        <th style="padding: 10px; text-align: left;">Line #</th>
                        <th style="padding: 10px; text-align: left;">Category</th>
                        <th style="padding: 10px; text-align: left;">Product</th>
                        <th style="padding: 10px; text-align: right;">Quantity</th>
                        <th style="padding: 10px; text-align: right;">Unit Price</th>
                        <th style="padding: 10px; text-align: right;">Total</th>
                    </tr>
                </thead>
                <tbody>
            """
            
            items_text = "\nYOUR QUOTED ITEMS:\n"
            items_text += "-" * 80 + "\n"
            
            for quote in quotations:
                line_num = quote.get('line_number', 'N/A')
                category = quote.get('original_request', {}).get('category', 'N/A')
                
                for product in quote.get('offered_products', []):
                    product_name = product.get('product_name', 'N/A')
                    quantity = product.get('quantity', 0)
                    unit_price = product.get('unit_price', 0)
                    total_price = product.get('total_price', 0)
                    
                    items_html += f"""
                        <tr style="border-bottom: 1px solid #ddd;">
                            <td style="padding: 8px;">{line_num}</td>
                            <td style="padding: 8px;">{category}</td>
                            <td style="padding: 8px;">{product_name}</td>
                            <td style="padding: 8px; text-align: right;">{quantity}</td>
                            <td style="padding: 8px; text-align: right;">{data[3]} {unit_price:,.2f}</td>
                            <td style="padding: 8px; text-align: right;">{data[3]} {total_price:,.2f}</td>
                        </tr>
                    """
                    
                    items_text += f"  Line {line_num}: {category} - {product_name}\n"
                    items_text += f"    Quantity: {quantity} | Unit Price: {data[3]} {unit_price:,.2f} | Total: {data[3]} {total_price:,.2f}\n"
            
            items_html += "</tbody></table>"
        else:
            items_html = "<p>No quoted items found.</p>"
            items_text = "No quoted items found.\n"
        
        # Build other bids table
        other_bids_html = ""
        if other_bids:
            other_bids_html = """
            <h3>🏆 Other Bids Received</h3>
            <table style="width:100%; border-collapse: collapse; margin: 20px 0;">
                <thead>
                    <tr style="background-color: #6c757d; color: white;">
                        <th style="padding: 8px; text-align: left;">Supplier</th>
                        <th style="padding: 8px; text-align: right;">Bid Amount</th>
                    </tr>
                </thead>
                <tbody>
            """
            for bid in other_bids:
                other_bids_html += f"""
                    <tr style="border-bottom: 1px solid #ddd;">
                        <td style="padding: 8px;">{bid[0]}</td>
                        <td style="padding: 8px; text-align: right;">{bid[2]} {float(bid[1]):,.2f}</td>
                    </tr>
                """
            other_bids_html += "</tbody></table>"
        
        # Email HTML
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                .container {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; }}
                .header {{ background: linear-gradient(135deg, #10b981, #059669); color: white; padding: 30px 20px; text-align: center; }}
                .content {{ padding: 30px 20px; background-color: #f9f9f9; }}
                .winner-badge {{ background-color: #fbbf24; color: #1e293b; padding: 10px 20px; border-radius: 50px; 
                            font-weight: bold; display: inline-block; margin: 20px 0; }}
                .info-box {{ background-color: white; padding: 20px; border-radius: 10px; margin: 20px 0; 
                            border-left: 4px solid #10b981; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
                .button {{ display: inline-block; padding: 12px 24px; background-color: #10b981; color: white; 
                        text-decoration: none; border-radius: 5px; font-weight: bold; }}
                .footer {{ background-color: #e9e9e9; padding: 20px; text-align: center; font-size: 12px; color: #666; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th {{ background-color: #f0f0f0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎉 Congratulations!</h1>
                    <h2>Your Bid Has Been Selected</h2>
                </div>
                
                <div class="content">
                    <div style="text-align: center;">
                        <span class="winner-badge">WINNING BID</span>
                    </div>
                    
                    <p>Dear <strong>{data[7] or data[6]}</strong>,</p>
                    
                    <p>We are pleased to inform you that your bid for <strong>RFX {data[0]}</strong> has been 
                    selected as the winning bid. After careful evaluation of all submissions, your proposal 
                    stood out as the most competitive and best suited to our requirements.</p>
                    
                    <div class="info-box">
                        <h3>📋 Award Summary</h3>
                        <table style="width:100%; margin-top: 10px;">
                            <tr>
                                <td><strong>RFX ID:</strong></td>
                                <td>{data[0]}</td>
                            </tr>
                            <tr>
                                <td><strong>Department:</strong></td>
                                <td>{data[9] or 'N/A'}</td>
                            </tr>
                            <tr>
                                <td><strong>Award Date:</strong></td>
                                <td>{award_date}</td>
                            </tr>
                            <tr>
                                <td><strong>Total Bid Amount:</strong></td>
                                <td><strong>{data[3]} {formatted_amount}</strong></td>
                            </tr>
                            <tr>
                                <td><strong>Required Date:</strong></td>
                                <td>{required_date}</td>
                            </tr>
                            <tr>
                                <td><strong>Delivery Deadline:</strong></td>
                                <td>{delivery_deadline}</td>
                            </tr>
                        </table>
                    </div>
                    
                    {items_html}
                    
                    {other_bids_html}
                    
                    <div class="info-box" style="border-left-color: #3b82f6;">
                        <h3>📝 Next Steps</h3>
                        <ol style="margin-top: 10px; padding-left: 20px;">
                            <li>You will receive a formal purchase order within 2-3 business days</li>
                            <li>Please prepare to fulfill the order according to your quoted delivery timeline</li>
                            <li>Our procurement team will contact you to finalize delivery arrangements</li>
                            <li>Ensure all necessary documentation and certifications are ready</li>
                        </ol>
                    </div>
                    
                    <p style="margin-top: 30px;">If you have any questions about this award or need to discuss 
                    any aspect of your bid, please don't hesitate to contact our procurement team.</p>
                    
                    <p style="margin-top: 30px; text-align: center;">
                        <a href="{self.base_url}" class="button">Visit Procurement Portal</a>
                    </p>
                </div>
                
                <div class="footer">
                    <p>This is an automated message from the Procurement System. Please do not reply to this email.</p>
                    <p>&copy; {datetime.now().year} Procurement Department. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_body = f"""
        ========================================
        🎉 CONGRATULATIONS! YOUR BID HAS BEEN SELECTED
        ========================================
        
        Dear {data[7] or data[6]},
        
        We are pleased to inform you that your bid for RFX {data[0]} has been selected as the winning bid.
        
        AWARD SUMMARY:
        --------------
        RFX ID: {data[0]}
        Department: {data[9] or 'N/A'}
        Award Date: {award_date}
        Total Bid Amount: {data[3]} {formatted_amount}
        Required Date: {required_date}
        Delivery Deadline: {delivery_deadline}
        
        {items_text}
        
        NEXT STEPS:
        -----------
        1. You will receive a formal purchase order within 2-3 business days
        2. Please prepare to fulfill the order according to your quoted delivery timeline
        3. Our procurement team will contact you to finalize delivery arrangements
        4. Ensure all necessary documentation and certifications are ready
        
        If you have any questions, please contact our procurement team.
        
        Visit our portal: {self.base_url}
        
        ========================================
        This is an automated message from the Procurement System.
        ========================================
        """
        
        return {
            "status": "success",
            "to_email": data[8],
            "to_name": data[7] or data[6],
            "subject": f"🎉 Congratulations! Your Bid for RFX {data[0]} Has Been Selected",
            "html_body": html_body,
            "text_body": text_body,
            "rfq_id": data[0],
            "mapping_id": mapping_id,
            "supplier_name": data[6]
        }

    def send_email(self, to_email: str, subject: str, html_body: str, text_body: str = None) -> bool:
        """
        Send email using SMTP configuration
        Returns True if successful, False otherwise
        """
        if not all([self.smtp_host, self.smtp_port, self.smtp_user, self.smtp_pass]):
            logger.error("Email configuration incomplete. Check SMTP_* environment variables.")
            return False
        
        try:
            msg = EmailMessage()
            msg["From"] = formataddr((self.sender_name, self.smtp_user))
            msg["To"] = to_email
            msg["Subject"] = subject
            
            # Set plain text version
            if text_body:
                msg.set_content(text_body)
            
            # Add HTML version
            msg.add_alternative(html_body, subtype='html')
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    